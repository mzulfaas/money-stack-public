"""Configuration loader for money-stack-public.

Loads environment variables (.env), account policies (config/accounts.json),
and content guardrails (config/rules.json) with safe fallback defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_RULES: Dict[str, Any] = {
    "default_tz_offset_hours": 7,
    "platform_char_limits": {
        "twitter": 250,
        "threads": 490,
        "instagram": 2200,
        "facebook": 5000,
    },
    "forbidden_ai_slop_phrases": [
        "game changer",
        "game-changer",
        "holy grail",
        "in today's fast-paced world",
        "as an ai",
        "delve into",
        "tapestry of",
        "banyak yang nanya",
        "banyak yg nanya",
        "sering ditanya",
    ],
    "forbidden_punctuation": ["—", "–"],
    "forbidden_emojis": ["✨"],
    "tracked_shortlink_domains": ["s.shopee.co.id", "shope.ee"],
    "require_zero_hashtag_platforms": ["threads"],
    "allow_root_links": False,
}


@dataclass(frozen=True)
class AccountPolicy:
    """Per-account publishing, pacing, and monetization policy."""

    account_id: str
    platform: str
    handle: str
    shortcode: str
    daily_cap: int = 3
    min_interval_m: int = 180
    language: str = "en"
    monetization: Optional[str] = None
    no_selling: bool = False
    blocked_domains: Tuple[str, ...] = ()
    forbidden_keywords: Tuple[str, ...] = ()
    blocked_via_scheduler: bool = False
    blocked_reason: str = ""


@dataclass
class StackConfig:
    """Resolved workspace configuration paths and policies."""

    root_dir: Path
    config_dir: Path
    data_dir: Path
    tz_offset_hours: int = 7
    accounts: Dict[str, AccountPolicy] = field(default_factory=dict)
    rules: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RULES))


def load_dotenv(env_path: Optional[Path] = None) -> None:
    """Loads key=value pairs from .env without overriding existing process env."""
    if env_path is None:
        env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def parse_accounts_payload(payload: Dict[str, Any]) -> Dict[str, AccountPolicy]:
    """Parses raw JSON account registry into normalized AccountPolicy instances."""
    raw_accounts = payload.get("accounts", {})
    parsed: Dict[str, AccountPolicy] = {}
    if not isinstance(raw_accounts, dict):
        return parsed

    for account_id, item in raw_accounts.items():
        if not isinstance(item, dict):
            continue
        clean_id = account_id.strip().lower()
        parsed[clean_id] = AccountPolicy(
            account_id=clean_id,
            platform=str(item.get("platform", "unknown")).lower(),
            handle=str(item.get("handle", f"acc_{clean_id[:8]}")),
            shortcode=str(item.get("shortcode", f"GEN_{clean_id[:6].upper()}")),
            daily_cap=int(item.get("daily_cap", 3)),
            min_interval_m=int(item.get("min_interval_m", 180)),
            language=str(item.get("language", "en")).lower(),
            monetization=item.get("monetization"),
            no_selling=bool(item.get("no_selling", False)),
            blocked_domains=tuple(str(d).lower() for d in item.get("blocked_domains", [])),
            forbidden_keywords=tuple(str(k).lower() for k in item.get("forbidden_keywords", [])),
            blocked_via_scheduler=bool(item.get("blocked_via_scheduler", False)),
            blocked_reason=str(item.get("blocked_reason", "")),
        )
    return parsed


def load_stack_config(
    root_dir: Optional[Path] = None,
    accounts_path: Optional[Path] = None,
    rules_path: Optional[Path] = None,
) -> StackConfig:
    """Resolves directories, account policies, and lint rules."""
    resolved_root = (root_dir or Path.cwd()).resolve()
    load_dotenv(resolved_root / ".env")

    config_dir = Path(os.environ.get("MONEY_STACK_CONFIG_DIR", resolved_root / "config")).resolve()
    data_dir = Path(os.environ.get("MONEY_STACK_DATA_DIR", resolved_root / "data")).resolve()
    tz_offset = int(os.environ.get("MONEY_STACK_TZ_OFFSET_HOURS", DEFAULT_RULES["default_tz_offset_hours"]))

    resolved_accounts = accounts_path or (config_dir / "accounts.json")
    accounts: Dict[str, AccountPolicy] = {}
    if resolved_accounts.is_file():
        accounts = parse_accounts_payload(_read_json(resolved_accounts))

    resolved_rules = rules_path or (config_dir / "rules.json")
    rules = dict(DEFAULT_RULES)
    if resolved_rules.is_file():
        loaded_rules = _read_json(resolved_rules)
        rules.update(loaded_rules)

    return StackConfig(
        root_dir=resolved_root,
        config_dir=config_dir,
        data_dir=data_dir,
        tz_offset_hours=tz_offset,
        accounts=accounts,
        rules=rules,
    )
