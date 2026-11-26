"""REST API client for Tebar.app social media scheduling and analytics.

Sign up / obtain an API key at: https://tebar.app/?ref=BLASTER
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from money_stack import TEBAR_API_BASE_URL, TEBAR_REFERRAL_URL
from money_stack.config import StackConfig, load_stack_config
from money_stack.storage.fleet_db import record_publication
from money_stack.tebar.pacing_guard import PacingSubidGuard


class TebarAuthError(RuntimeError):
    """Raised when TEBAR_API_KEY is missing or rejected."""


class TebarAPIError(RuntimeError):
    """Raised on non-2xx Tebar REST API responses."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Tebar API Error {status_code}: {message}")


class TebarClient:
    """Clean REST client for Tebar.app with integrated preflight guardrails."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[StackConfig] = None,
        guard: Optional[PacingSubidGuard] = None,
        db_path: Optional[Path] = None,
    ):
        self.config = config or load_stack_config()
        resolved_key = (api_key or os.environ.get("TEBAR_API_KEY") or "").strip()
        if not resolved_key or resolved_key == "your_tebar_api_key_here":
            raise TebarAuthError(
                "TEBAR_API_KEY is not configured. "
                f"Create an account and generate your API key at {TEBAR_REFERRAL_URL}, "
                "then set TEBAR_API_KEY in your .env file."
            )
        self.api_key = resolved_key
        self.base_url = (base_url or os.environ.get("TEBAR_BASE_URL") or TEBAR_API_BASE_URL).rstrip("/")
        self.db_path = db_path
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "MoneyStackPublic/0.1",
        }
        self.guard = guard or PacingSubidGuard(
            config=self.config,
            posts_fetcher=lambda acc_id: self.list_posts(account_id=acc_id, limit=50).get("data", []),
        )

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = dict(self.headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            raw_err = err.read().decode("utf-8", errors="replace")
            raise TebarAPIError(err.code, raw_err) from err
        except Exception as exc:
            raise RuntimeError(f"Tebar request failed ({method} {endpoint}): {exc}") from exc

    def list_accounts(self) -> List[Dict[str, Any]]:
        return self._request("/accounts", method="GET").get("data", [])

    def list_profiles(self) -> Dict[str, Any]:
        return self._request("/profiles", method="GET")

    def list_posts(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        exclude_status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        params = [f"limit={limit}"]
        if account_id:
            params.append(f"account_id={urllib.parse.quote(account_id)}")
        if status:
            params.append(f"status={urllib.parse.quote(status)}")
        if exclude_status:
            params.append(f"exclude_status={urllib.parse.quote(exclude_status)}")
        if cursor:
            params.append(f"cursor={urllib.parse.quote(cursor)}")
        return self._request(f"/posts?{'&'.join(params)}", method="GET")

    def get_post(self, post_id: str) -> Dict[str, Any]:
        return self._request(f"/posts/{post_id}", method="GET")

    def get_post_insights(self, post_id: str) -> Dict[str, Any]:
        return self._request(f"/posts/{post_id}/insights", method="GET")

    def cancel_scheduled_post(self, post_id: str) -> Dict[str, Any]:
        return self._request(f"/posts/{post_id}", method="DELETE")

    def list_media(
        self,
        media_type: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        params = [f"limit={limit}"]
        if media_type:
            params.append(f"type={urllib.parse.quote(media_type)}")
        if cursor:
            params.append(f"cursor={urllib.parse.quote(cursor)}")
        return self._request(f"/media?{'&'.join(params)}", method="GET")

    def list_links(self, cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        params = [f"limit={limit}"]
        if cursor:
            params.append(f"cursor={urllib.parse.quote(cursor)}")
        return self._request(f"/links?{'&'.join(params)}", method="GET")

    def create_link(self, url: str, title: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"url": url}
        if title:
            payload["title"] = title
        return self._request("/links", method="POST", data=payload)

    def get_or_create_link(self, url: str, title: Optional[str] = None) -> Dict[str, Any]:
        clean = url.strip().rstrip("/")
        for item in self.list_links(limit=50).get("data", []):
            target = str(item.get("url") or "").strip().rstrip("/")
            if target == clean and item.get("status") == "active":
                return item
        return self.create_link(url, title=title)

    def get_account_insights(self, account_id: str, days: int = 30) -> Dict[str, Any]:
        return self._request(f"/accounts/{account_id}/insights?days={days}", method="GET")

    def get_best_times(self, account_id: str, tz: str = "Asia/Jakarta") -> Dict[str, Any]:
        return self._request(
            f"/accounts/{account_id}/best-times?tz={urllib.parse.quote(tz, safe='')}",
            method="GET",
        )

    def _record_acceptance(
        self,
        account_id: str,
        content: str,
        response: Dict[str, Any],
        scheduled_at: Optional[str],
        publication_record: Optional[Dict[str, Any]],
    ) -> None:
        if not publication_record:
            return
        sku = str(publication_record.get("sku") or "").strip()
        if not sku:
            return
        db_target = Path(publication_record.get("db_path") or self.db_path or (self.config.data_dir / "fleet_central.db"))
        policy = self.guard.get_account_policy(account_id)
        meta = {
            "tebar_post_id": response.get("id"),
            "tebar_status": response.get("status") or "scheduled",
            "evidence": "SCHEDULED",
        }
        if isinstance(publication_record.get("metadata"), dict):
            meta.update(publication_record["metadata"])

        record_publication(
            db_path=db_target,
            sku=sku,
            platform=str(publication_record.get("platform") or policy.platform),
            account_handle=str(publication_record.get("account_handle") or policy.handle),
            root_text=content,
            device_id=str(publication_record.get("device_id") or "tebar_api"),
            shortlink=str(publication_record.get("shortlink") or ""),
            sub_id=str(publication_record.get("sub_id") or ""),
            post_url=str(publication_record.get("post_url") or ""),
            media_path=publication_record.get("media_path"),
            media_dhash=publication_record.get("media_dhash"),
            published_at=scheduled_at or publication_record.get("published_at"),
            status="SCHEDULED",
            metadata=meta,
        )

    def create_threads_post(
        self,
        account_id: str,
        content: str,
        topic_tag: Optional[str] = None,
        thread_parts: Optional[List[str]] = None,
        media_urls: Optional[List[str]] = None,
        scheduled_at: Optional[str] = None,
        is_made_with_ai: bool = False,
        bypass_pacing: bool = False,
        is_affiliate: bool = True,
        publication_record: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        preflight = self.guard.validate_and_sanitize(
            account_id=account_id,
            content=content,
            scheduled_at=scheduled_at,
            format_type="THREAD",
            reply_thread=thread_parts,
            bypass_pacing=bypass_pacing,
            is_affiliate=is_affiliate,
        )
        options: Dict[str, Any] = {"is_made_with_ai": bool(is_made_with_ai)}
        if topic_tag:
            options["topic_tag"] = topic_tag.replace("#", "").strip()
        if preflight.reply_thread:
            options["thread"] = preflight.reply_thread

        payload: Dict[str, Any] = {
            "content": preflight.content,
            "targets": [{"account_id": account_id, "options": options}],
        }
        if media_urls:
            payload["media_urls"] = media_urls
        if scheduled_at:
            payload["scheduled_at"] = scheduled_at

        res = self._request("/posts", method="POST", data=payload, idempotency_key=str(uuid.uuid4()))
        self._record_acceptance(account_id, preflight.content, res, scheduled_at, publication_record)
        return res

    def create_omnichannel_post(
        self,
        account_id: str,
        content: str,
        media_ids: Optional[List[str]] = None,
        scheduled_at: Optional[str] = None,
        format_type: str = "CARD",
        facebook_link: Optional[str] = None,
        reply_thread: Optional[List[str]] = None,
        target_options: Optional[Dict[str, Any]] = None,
        bypass_pacing: bool = False,
        is_affiliate: bool = True,
        publication_record: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raw_options = dict(target_options or {})
        policy = self.guard.get_account_policy(account_id)
        preflight = self.guard.validate_and_sanitize(
            account_id=account_id,
            content=content,
            media_ids=media_ids,
            scheduled_at=scheduled_at,
            format_type=format_type,
            facebook_link=facebook_link,
            reply_thread=reply_thread,
            first_comment=raw_options.get("first_comment"),
            bypass_pacing=bypass_pacing,
            is_affiliate=is_affiliate,
        )

        options: Dict[str, Any] = {}
        platform = policy.platform
        if platform == "instagram":
            if format_type.upper() in ("REEL", "VIDEO") and len(media_ids or []) == 1:
                options["share_to_feed"] = bool(raw_options.get("share_to_feed", True))
                if "thumb_offset_ms" in raw_options:
                    options["thumb_offset_ms"] = int(raw_options["thumb_offset_ms"])
            if "is_ai_generated" in raw_options or "is_made_with_ai" in raw_options:
                options["is_ai_generated"] = bool(
                    raw_options.get("is_ai_generated", raw_options.get("is_made_with_ai"))
                )
            if preflight.first_comment:
                options["first_comment"] = preflight.first_comment
            elif preflight.reply_thread:
                options["first_comment"] = preflight.reply_thread[0]

        elif platform == "threads":
            if preflight.reply_thread:
                options["thread"] = preflight.reply_thread
            elif preflight.first_comment:
                options["thread"] = [preflight.first_comment]
            if "topic_tag" in raw_options:
                options["topic_tag"] = str(raw_options["topic_tag"]).replace("#", "").strip()
            if "is_made_with_ai" in raw_options or "is_ai_generated" in raw_options:
                options["is_made_with_ai"] = bool(
                    raw_options.get("is_made_with_ai", raw_options.get("is_ai_generated"))
                )

        elif platform == "facebook":
            if preflight.facebook_link:
                options["link"] = preflight.facebook_link
            elif "link" in raw_options:
                options["link"] = raw_options["link"]
            if "video_as" in raw_options:
                options["video_as"] = str(raw_options["video_as"]).lower()
            if preflight.first_comment:
                options["first_comment"] = preflight.first_comment
            elif preflight.reply_thread:
                options["first_comment"] = preflight.reply_thread[0]

        elif platform == "pinterest":
            for key in ("board_id", "title", "link", "cover_media_id"):
                if key in raw_options:
                    options[key] = str(raw_options[key])
        else:
            options = raw_options

        payload: Dict[str, Any] = {
            "content": preflight.content,
            "targets": [{"account_id": account_id, "options": options}],
        }
        if media_ids:
            payload["media_ids"] = media_ids
        if scheduled_at:
            payload["scheduled_at"] = scheduled_at

        res = self._request("/posts", method="POST", data=payload, idempotency_key=str(uuid.uuid4()))
        self._record_acceptance(account_id, preflight.content, res, scheduled_at, publication_record)
        return res
