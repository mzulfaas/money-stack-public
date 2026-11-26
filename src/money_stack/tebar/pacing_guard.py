"""Pacing, frequency, cross-niche firewall, and SubID injection guardrails."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from money_stack.audit.pre_post_gate import PrePostAuditError, assert_post_safe
from money_stack.audit.subid_resolver import (
    DEFAULT_TRACKED_DOMAINS,
    FastUrlVerifier,
    URL_EXTRACT_RE,
    inject_subid,
    sanitize_links_in_text,
)
from money_stack.config import AccountPolicy, StackConfig

logger = logging.getLogger("money_stack.pacing")


class FatalPacingViolation(RuntimeError):
    """Raised when a candidate post violates pacing, domain, niche, or link rules."""


@dataclass
class PreflightResult:
    account_id: str
    content: str
    facebook_link: Optional[str] = None
    reply_thread: List[str] = field(default_factory=list)
    first_comment: Optional[str] = None
    scheduled_at: Optional[str] = None
    media_ids: List[str] = field(default_factory=list)
    status: str = "APPROVED"


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


class PacingSubidGuard:
    """Enforces account policies, spacing/daily caps, link safety, and canonical SubIDs."""

    def __init__(
        self,
        config: StackConfig,
        posts_fetcher: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
        url_verifier: Optional[FastUrlVerifier] = None,
    ):
        self.config = config
        self.posts_fetcher = posts_fetcher
        self.url_verifier = url_verifier

    def get_account_policy(self, account_id: str) -> AccountPolicy:
        clean = account_id.strip().lower()
        if clean in self.config.accounts:
            return self.config.accounts[clean]
        return AccountPolicy(
            account_id=clean,
            platform="unknown",
            handle=f"acc_{clean[:8]}",
            shortcode=f"GEN_{clean[:6].upper()}",
        )

    def assert_account_policy(
        self,
        policy: AccountPolicy,
        texts: Sequence[str],
        external_link: Optional[str] = None,
        is_affiliate: bool = True,
    ) -> None:
        if policy.blocked_via_scheduler:
            reason = policy.blocked_reason or "Account is configured to block API scheduler publishing."
            raise FatalPacingViolation(f"SCHEDULER_BLOCKED ({policy.handle}): {reason}")

        combined = "\n".join([*(t for t in texts if t), external_link or ""]).lower()
        urls_present = URL_EXTRACT_RE.findall(combined)

        if policy.no_selling and (urls_present or (is_affiliate and external_link)):
            raise FatalPacingViolation(
                f"NO_SELLING_POLICY ({policy.handle}): Outbound/affiliate links are disabled for this account."
            )

        for domain in policy.blocked_domains:
            if domain in combined:
                raise FatalPacingViolation(
                    f"BLOCKED_DOMAIN ({policy.handle}): Domain '{domain}' is forbidden by account policy."
                )

        for kw in policy.forbidden_keywords:
            if kw in combined:
                raise FatalPacingViolation(
                    f"NICHE_FIREWALL ({policy.handle}): Forbidden keyword '{kw}' detected."
                )

    def assert_links_alive(self, texts: Sequence[Optional[str]]) -> None:
        if self.url_verifier is None:
            return
        tracked = {
            d.lower() for d in self.config.rules.get("tracked_shortlink_domains", DEFAULT_TRACKED_DOMAINS)
        }
        seen = set()
        for text in texts:
            if not text:
                continue
            for url in URL_EXTRACT_RE.findall(text):
                if any(dom in url.lower() for dom in tracked) and url not in seen:
                    seen.add(url)
                    alive, code, loc = self.url_verifier.check_alive(url)
                    if not alive:
                        raise FatalPacingViolation(
                            f"DEAD_SHORTLINK: {url} failed health check (HTTP {code}, location={loc!r})."
                        )

    def check_pacing_and_frequency(
        self,
        account_id: str,
        target_dt: Optional[datetime] = None,
        post_type: str = "text",
    ) -> Tuple[bool, str]:
        policy = self.get_account_policy(account_id)
        min_interval = policy.min_interval_m if post_type == "video" else min(policy.min_interval_m, 120)
        ref_dt = target_dt or datetime.now(timezone.utc)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        if self.posts_fetcher is None:
            return True, "NO_FETCHER_CONFIGURED"

        try:
            posts = self.posts_fetcher(account_id)
        except Exception as exc:
            logger.warning("Skipping live pacing check (fetch failed): %s", exc)
            return True, "API_UNAVAILABLE_FALLBACK"

        tz = timezone(timedelta(hours=self.config.tz_offset_hours))
        target_day = ref_dt.astimezone(tz).date()
        day_count = 0

        for post in posts:
            if str(post.get("status", "")).lower() == "canceled":
                continue
            p_dt = _parse_iso_dt(
                post.get("scheduled_at") or post.get("published_at") or post.get("created_at")
            )
            if p_dt is None:
                continue

            if p_dt.astimezone(tz).date() == target_day:
                day_count += 1

            diff_minutes = abs((ref_dt - p_dt).total_seconds()) / 60.0
            if diff_minutes < min_interval:
                return (
                    False,
                    f"PACING_VIOLATION ({policy.handle}): {diff_minutes:.1f}m gap from post {post.get('id')} "
                    f"is below minimum {min_interval}m.",
                )

        if day_count >= policy.daily_cap:
            return (
                False,
                f"DAILY_CAP_EXCEEDED ({policy.handle}): {day_count}/{policy.daily_cap} posts on {target_day.isoformat()}.",
            )

        return True, f"PASSED ({policy.handle}): {day_count}/{policy.daily_cap} posts used."

    def validate_and_sanitize(
        self,
        account_id: str,
        content: str,
        media_ids: Optional[List[str]] = None,
        scheduled_at: Optional[str] = None,
        format_type: str = "CARD",
        facebook_link: Optional[str] = None,
        reply_thread: Optional[List[str]] = None,
        first_comment: Optional[str] = None,
        bypass_pacing: bool = False,
        is_affiliate: bool = True,
    ) -> PreflightResult:
        policy = self.get_account_policy(account_id)
        all_texts = [content, *(reply_thread or []), *([first_comment] if first_comment else [])]

        try:
            assert_post_safe(
                all_texts,
                platform=policy.platform,
                is_affiliate=is_affiliate,
                rules=self.config.rules,
            )
        except PrePostAuditError as exc:
            raise FatalPacingViolation(str(exc)) from exc

        self.assert_account_policy(
            policy,
            texts=all_texts,
            external_link=facebook_link,
            is_affiliate=is_affiliate,
        )
        self.assert_links_alive([*all_texts, facebook_link])

        target_dt = _parse_iso_dt(scheduled_at)
        if not bypass_pacing:
            post_type = "video" if media_ids else "text"
            ok, msg = self.check_pacing_and_frequency(account_id, target_dt=target_dt, post_type=post_type)
            if not ok:
                raise FatalPacingViolation(msg)

        tracked_domains = self.config.rules.get("tracked_shortlink_domains", DEFAULT_TRACKED_DOMAINS)
        tz_offset = self.config.tz_offset_hours

        sanitized_content = sanitize_links_in_text(
            content,
            shortcode=policy.shortcode,
            format_type=format_type,
            target_dt=target_dt,
            tracked_domains=tracked_domains,
            tz_offset_hours=tz_offset,
        )
        sanitized_fb = (
            inject_subid(
                facebook_link,
                shortcode=policy.shortcode,
                format_type="CARD",
                target_dt=target_dt,
                tracked_domains=tracked_domains,
                tz_offset_hours=tz_offset,
            )
            if facebook_link
            else None
        )
        sanitized_replies = [
            sanitize_links_in_text(
                item,
                shortcode=policy.shortcode,
                format_type="REPLY",
                target_dt=target_dt,
                tracked_domains=tracked_domains,
                tz_offset_hours=tz_offset,
            )
            for item in (reply_thread or [])
        ]
        sanitized_comment = (
            sanitize_links_in_text(
                first_comment,
                shortcode=policy.shortcode,
                format_type="REPLY",
                target_dt=target_dt,
                tracked_domains=tracked_domains,
                tz_offset_hours=tz_offset,
            )
            if first_comment
            else None
        )

        return PreflightResult(
            account_id=account_id,
            content=sanitized_content,
            facebook_link=sanitized_fb,
            reply_thread=sanitized_replies,
            first_comment=sanitized_comment,
            scheduled_at=scheduled_at,
            media_ids=list(media_ids or []),
        )
