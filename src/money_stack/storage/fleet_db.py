"""Centralized SQLite WAL ledger and atomic task lease engine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_text(text: str) -> str:
    """Computes a whitespace-normalized SHA-256 hash of caption text."""
    normalized = " ".join((text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@contextmanager
def get_db_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Provides a thread-safe SQLite connection configured with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Initializes the publications ledger and atomic task lease tables."""
    with get_db_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                platform TEXT NOT NULL,
                account_handle TEXT NOT NULL,
                device_id TEXT,
                shortlink TEXT,
                sub_id TEXT,
                post_url TEXT,
                root_text TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                media_path TEXT,
                media_dhash TEXT,
                published_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'SCHEDULED',
                metadata_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pub_sku ON publications(sku);
            CREATE INDEX IF NOT EXISTS idx_pub_account ON publications(account_handle, published_at);
            CREATE INDEX IF NOT EXISTS idx_pub_platform ON publications(platform, published_at);
            CREATE INDEX IF NOT EXISTS idx_pub_text_hash ON publications(text_hash);

            CREATE TABLE IF NOT EXISTS active_leases (
                lease_id TEXT PRIMARY KEY,
                resource_key TEXT NOT NULL UNIQUE,
                platform TEXT NOT NULL,
                account_handle TEXT NOT NULL,
                worker_pid INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leases_expires ON active_leases(expires_at);
            """
        )


def record_publication(
    db_path: Path,
    sku: str,
    platform: str,
    account_handle: str,
    root_text: str,
    device_id: str = "tebar_api",
    shortlink: str = "",
    sub_id: str = "",
    post_url: str = "",
    media_path: Optional[str] = None,
    media_dhash: Optional[str] = None,
    published_at: Optional[str] = None,
    status: str = "SCHEDULED",
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """Records a scheduled or published post in the SQLite ledger and returns row ID."""
    init_db(db_path)
    ts = published_at or _now_utc().isoformat()
    meta_str = json.dumps(metadata or {}, ensure_ascii=False)
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO publications (
                sku, platform, account_handle, device_id, shortlink, sub_id,
                post_url, root_text, text_hash, media_path, media_dhash,
                published_at, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sku,
                platform.lower(),
                account_handle,
                device_id,
                shortlink,
                sub_id,
                post_url,
                root_text,
                hash_text(root_text),
                media_path,
                media_dhash,
                ts,
                status,
                meta_str,
            ),
        )
        return int(cur.lastrowid)


def has_recent_publication(
    db_path: Path,
    sku: str,
    platform: str,
    cooldown_days: int = 30,
) -> bool:
    """Checks if a given SKU was already published/scheduled on a platform within cooldown_days."""
    if not db_path.exists():
        return False
    cutoff = (_now_utc() - timedelta(days=cooldown_days)).isoformat()
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM publications
            WHERE sku = ? AND platform = ? AND status != 'CANCELED' AND published_at >= ?
            LIMIT 1
            """,
            (sku, platform.lower(), cutoff),
        ).fetchone()
        return row is not None


def acquire_lease(
    db_path: Path,
    resource_key: str,
    platform: str,
    account_handle: str,
    worker_pid: int,
    ttl_seconds: int = 300,
) -> Optional[str]:
    """Acquires an exclusive task lease for resource_key, pruning expired leases first."""
    init_db(db_path)
    now = _now_utc()
    expires = now + timedelta(seconds=ttl_seconds)
    lease_id = str(uuid.uuid4())
    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM active_leases WHERE expires_at <= ?", (now.isoformat(),))
        try:
            conn.execute(
                """
                INSERT INTO active_leases (
                    lease_id, resource_key, platform, account_handle,
                    worker_pid, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease_id,
                    resource_key,
                    platform.lower(),
                    account_handle,
                    worker_pid,
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
            return lease_id
        except sqlite3.IntegrityError:
            return None


def release_lease(db_path: Path, lease_id: str) -> bool:
    """Releases an active lease by ID."""
    if not db_path.exists():
        return False
    with get_db_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM active_leases WHERE lease_id = ?", (lease_id,))
        return cur.rowcount > 0
