"""Canonical SubID generator, link injector, and SQLite-cached URL health verifier."""

from __future__ import annotations

import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple


DEFAULT_TRACKED_DOMAINS = ("s.shopee.co.id", "shope.ee")
URL_EXTRACT_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")


def generate_canonical_subid(
    shortcode: str,
    format_type: str = "CARD",
    target_dt: Optional[datetime] = None,
    tz_offset_hours: int = 7,
) -> str:
    """Builds canonical SubID formatted as {SHORTCODE}_{FORMAT}_{YYMMDD}."""
    clean_shortcode = re.sub(r"[^A-Za-z0-9_]", "", shortcode.strip().upper()) or "GEN"
    clean_fmt = re.sub(r"[^A-Za-z0-9_]", "", format_type.strip().upper()) or "CARD"
    sub_id = f"{clean_shortcode}_{clean_fmt}"
    if target_dt is not None:
        if target_dt.tzinfo is None:
            dt_local = target_dt
        else:
            dt_local = target_dt.astimezone(timezone(timedelta(hours=tz_offset_hours)))
        sub_id = f"{sub_id}_{dt_local.strftime('%y%m%d')}"
    return sub_id[:50]


def inject_subid(
    url: str,
    shortcode: str,
    format_type: str = "CARD",
    target_dt: Optional[datetime] = None,
    tracked_domains: Iterable[str] = DEFAULT_TRACKED_DOMAINS,
    tz_offset_hours: int = 7,
) -> str:
    """Injects canonical ?sub_id=... into tracked shortlinks while preserving existing params."""
    clean_url = (url or "").strip()
    if not clean_url:
        return ""

    parsed = urllib.parse.urlsplit(clean_url)
    domain_set = {d.lower() for d in tracked_domains}
    if parsed.netloc.lower() not in domain_set:
        return clean_url

    canonical = generate_canonical_subid(shortcode, format_type, target_dt, tz_offset_hours)
    query_params = [
        (k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if k not in ("sub_id", "sub_id4")
    ]
    query_params.append(("sub_id", canonical))

    if not re.search(r"_\d{6}$", canonical):
        ref_dt = (target_dt or datetime.now(timezone.utc)).astimezone(
            timezone(timedelta(hours=tz_offset_hours))
        )
        query_params.append(("sub_id4", ref_dt.strftime("%y%m%d")))

    new_query = urllib.parse.urlencode(query_params)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def sanitize_links_in_text(
    text: str,
    shortcode: str,
    format_type: str = "CARD",
    target_dt: Optional[datetime] = None,
    tracked_domains: Iterable[str] = DEFAULT_TRACKED_DOMAINS,
    tz_offset_hours: int = 7,
) -> str:
    """Finds tracked shortlinks in text and rewrites them with canonical SubIDs."""
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = ""
        while raw and raw[-1] in ".,;:!?":
            suffix = raw[-1] + suffix
            raw = raw[:-1]
        updated = inject_subid(
            raw,
            shortcode=shortcode,
            format_type=format_type,
            target_dt=target_dt,
            tracked_domains=tracked_domains,
            tz_offset_hours=tz_offset_hours,
        )
        return f"{updated}{suffix}"

    return URL_EXTRACT_RE.sub(_replace, text)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class FastUrlVerifier:
    """Checks shortlink reachability without following tracking hops, backed by SQLite WAL cache."""

    def __init__(self, cache_db_path: Optional[Path] = None, ttl_seconds: int = 3600):
        self.cache_db_path = cache_db_path
        self.ttl_seconds = ttl_seconds
        if self.cache_db_path is not None:
            self._init_cache()

    def _init_cache(self) -> None:
        assert self.cache_db_path is not None
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.cache_db_path), timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS url_health_cache (
                    url TEXT PRIMARY KEY,
                    is_alive INTEGER NOT NULL,
                    status_code INTEGER NOT NULL,
                    location TEXT,
                    checked_at REAL NOT NULL
                )
                """
            )

    def _get_cached(self, url: str) -> Optional[Tuple[bool, int, str]]:
        if self.cache_db_path is None or not self.cache_db_path.exists():
            return None
        now = time.time()
        with sqlite3.connect(str(self.cache_db_path), timeout=10.0) as conn:
            row = conn.execute(
                "SELECT is_alive, status_code, location, checked_at FROM url_health_cache WHERE url = ?",
                (url,),
            ).fetchone()
            if row and (now - float(row[3])) <= self.ttl_seconds:
                return bool(row[0]), int(row[1]), str(row[2] or "")
        return None

    def _set_cached(self, url: str, is_alive: bool, status_code: int, location: str) -> None:
        if self.cache_db_path is None:
            return
        with sqlite3.connect(str(self.cache_db_path), timeout=10.0) as conn:
            conn.execute(
                """
                INSERT INTO url_health_cache (url, is_alive, status_code, location, checked_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    is_alive=excluded.is_alive,
                    status_code=excluded.status_code,
                    location=excluded.location,
                    checked_at=excluded.checked_at
                """,
                (url, int(is_alive), status_code, location, time.time()),
            )

    def check_alive(self, url: str, timeout: float = 8.0) -> Tuple[bool, int, str]:
        """Returns (is_alive, status_code, redirect_location). Flags 404/410 and error_page redirects."""
        cached = self._get_cached(url)
        if cached is not None:
            return cached

        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MoneyStackVerifier/0.1)"},
            method="HEAD",
        )
        try:
            with opener.open(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
                result = (code < 400, int(code), "")
        except urllib.error.HTTPError as err:
            loc = str(err.headers.get("Location", "") or "")
            is_dead = err.code in (404, 410) or "error_page" in loc.lower()
            result = (not is_dead and err.code < 400, int(err.code), loc)
        except Exception:
            return False, 0, ""

        self._set_cached(url, *result)
        return result
