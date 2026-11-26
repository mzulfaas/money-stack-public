"""Fail-closed pre-publish content linter and link isolation gate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from money_stack.audit.subid_resolver import URL_EXTRACT_RE
from money_stack.config import DEFAULT_RULES


class PrePostErrorCode(str, Enum):
    EMPTY_CONTENT = "EMPTY_CONTENT"
    CHAR_LIMIT_EXCEEDED = "CHAR_LIMIT_EXCEEDED"
    LINK_ISOLATION_VIOLATION = "LINK_ISOLATION_VIOLATION"
    INSECURE_LINK_PROTOCOL = "INSECURE_LINK_PROTOCOL"
    MULTIPLE_LINKS_DETECTED = "MULTIPLE_LINKS_DETECTED"
    BROKEN_URL_TYPO = "BROKEN_URL_TYPO"
    FORBIDDEN_SLOP_PHRASE = "FORBIDDEN_SLOP_PHRASE"
    FORBIDDEN_PUNCTUATION = "FORBIDDEN_PUNCTUATION"
    FORBIDDEN_EMOJI = "FORBIDDEN_EMOJI"
    HASHTAG_FORBIDDEN = "HASHTAG_FORBIDDEN"


@dataclass(frozen=True)
class AuditViolation:
    error_code: PrePostErrorCode
    message: str
    item_index: int
    snippet: Optional[str] = None


class PrePostAuditError(RuntimeError):
    """Raised when one or more pre-publish rules fail."""

    def __init__(self, violations: Sequence[AuditViolation]):
        self.violations = list(violations)
        summary = "; ".join(f"[{v.error_code.value}@{v.item_index}] {v.message}" for v in self.violations)
        super().__init__(summary)


def lint_post_sequence(
    items: Sequence[str],
    platform: str = "threads",
    is_affiliate: bool = True,
    rules: Optional[Dict[str, Any]] = None,
) -> List[AuditViolation]:
    """Lints a single post or multi-part thread/barbell funnel sequence (1-based index)."""
    cfg = dict(DEFAULT_RULES)
    if rules:
        cfg.update(rules)

    if not items:
        return [AuditViolation(PrePostErrorCode.EMPTY_CONTENT, "Post sequence cannot be empty.", 1)]

    violations: List[AuditViolation] = []
    platform_norm = platform.strip().lower()
    char_limit = int(cfg.get("platform_char_limits", {}).get(platform_norm, 2200))
    zero_hashtag_platforms = {p.lower() for p in cfg.get("require_zero_hashtag_platforms", [])}
    allow_root_links = bool(cfg.get("allow_root_links", False))
    total = len(items)

    for idx, raw_text in enumerate(items, start=1):
        text = (raw_text or "").strip()
        if not text:
            violations.append(AuditViolation(PrePostErrorCode.EMPTY_CONTENT, "Post item is empty.", idx))
            continue

        if len(text) > char_limit:
            violations.append(
                AuditViolation(
                    PrePostErrorCode.CHAR_LIMIT_EXCEEDED,
                    f"Length {len(text)} exceeds {platform_norm} limit of {char_limit} chars.",
                    idx,
                )
            )

        typo_match = re.search(r"[A-Za-z0-9]https?://", text)
        if typo_match:
            violations.append(
                AuditViolation(
                    PrePostErrorCode.BROKEN_URL_TYPO,
                    "Missing whitespace before URL.",
                    idx,
                    typo_match.group(0),
                )
            )

        text_lower = text.lower()
        for phrase in cfg.get("forbidden_ai_slop_phrases", []):
            if str(phrase).lower() in text_lower:
                violations.append(
                    AuditViolation(
                        PrePostErrorCode.FORBIDDEN_SLOP_PHRASE,
                        f"Forbidden cliche/slop phrase detected: '{phrase}'.",
                        idx,
                        str(phrase),
                    )
                )

        for punct in cfg.get("forbidden_punctuation", []):
            if punct in text:
                violations.append(
                    AuditViolation(
                        PrePostErrorCode.FORBIDDEN_PUNCTUATION,
                        f"Forbidden punctuation '{punct}' detected.",
                        idx,
                        punct,
                    )
                )

        for emoji in cfg.get("forbidden_emojis", []):
            if emoji in text:
                violations.append(
                    AuditViolation(
                        PrePostErrorCode.FORBIDDEN_EMOJI,
                        f"Forbidden emoji '{emoji}' detected.",
                        idx,
                        emoji,
                    )
                )

        if platform_norm in zero_hashtag_platforms:
            tag_match = re.search(r"#\w+", text)
            if tag_match:
                violations.append(
                    AuditViolation(
                        PrePostErrorCode.HASHTAG_FORBIDDEN,
                        f"Hashtag '{tag_match.group(0)}' forbidden on {platform_norm}; use native topic tag.",
                        idx,
                        tag_match.group(0),
                    )
                )

        urls = URL_EXTRACT_RE.findall(text)
        for url in urls:
            if url.lower().startswith("http://"):
                violations.append(
                    AuditViolation(
                        PrePostErrorCode.INSECURE_LINK_PROTOCOL,
                        "Insecure http:// URL detected; use https://.",
                        idx,
                        url,
                    )
                )

        if not is_affiliate and urls:
            violations.append(
                AuditViolation(
                    PrePostErrorCode.LINK_ISOLATION_VIOLATION,
                    "Organic post/thread must not contain outbound links.",
                    idx,
                    urls[0],
                )
            )
        elif is_affiliate and total > 1 and idx < total and not allow_root_links and urls:
            violations.append(
                AuditViolation(
                    PrePostErrorCode.LINK_ISOLATION_VIOLATION,
                    "2-step barbell funnel requires zero links in root/pre-final parts.",
                    idx,
                    urls[0],
                )
            )
        elif is_affiliate and idx == total and len(urls) > 1:
            violations.append(
                AuditViolation(
                    PrePostErrorCode.MULTIPLE_LINKS_DETECTED,
                    f"Expected at most 1 link in final item, found {len(urls)}.",
                    idx,
                )
            )

    return violations


def assert_post_safe(
    items: Sequence[str],
    platform: str = "threads",
    is_affiliate: bool = True,
    rules: Optional[Dict[str, Any]] = None,
) -> None:
    """Raises PrePostAuditError if any guardrail fails."""
    violations = lint_post_sequence(items, platform=platform, is_affiliate=is_affiliate, rules=rules)
    if violations:
        raise PrePostAuditError(violations)
