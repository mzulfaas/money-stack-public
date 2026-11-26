"""Command-line interface for money-stack-public."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from money_stack import TEBAR_REFERRAL_URL, __version__
from money_stack.adb.fleet import DeviceFleetManager
from money_stack.audit.pre_post_gate import PrePostAuditError, assert_post_safe
from money_stack.config import load_stack_config
from money_stack.media.video_dedup import check_video_for_duplicate, register_video_fingerprint
from money_stack.tebar.client import TebarAuthError, TebarClient


def _cmd_setup(args: argparse.Namespace) -> int:
    root = Path.cwd()
    env_example = root / ".env.example"
    env_live = root / ".env"
    if env_example.is_file() and not env_live.exists():
        shutil.copyfile(env_example, env_live)
        print(f"[+] Created {env_live} from .env.example")

    for name in ("accounts", "rules"):
        ex = root / "config" / f"{name}.example.json"
        live = root / "config" / f"{name}.json"
        if ex.is_file() and not live.exists():
            shutil.copyfile(ex, live)
            print(f"[+] Created {live} from {ex.name}")

    print("\nNext steps:")
    print(f"1. Sign up & get your Tebar.app API key: {TEBAR_REFERRAL_URL}")
    print("2. Put TEBAR_API_KEY=... inside .env")
    print("3. Customize config/accounts.json with your Tebar account UUIDs and policies")
    return 0


def _cmd_accounts(args: argparse.Namespace) -> int:
    cfg = load_stack_config()
    if args.live:
        client = TebarClient(config=cfg)
        accounts = client.list_accounts()
        print(json.dumps(accounts, indent=2, ensure_ascii=False))
        return 0
    summary = [
        {
            "account_id": acc.account_id,
            "platform": acc.platform,
            "handle": acc.handle,
            "shortcode": acc.shortcode,
            "daily_cap": acc.daily_cap,
            "min_interval_m": acc.min_interval_m,
            "blocked_via_scheduler": acc.blocked_via_scheduler,
        }
        for acc in cfg.accounts.values()
    ]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    cfg = load_stack_config()
    items = list(args.text)
    if args.reply:
        items.append(args.reply)
    try:
        assert_post_safe(items, platform=args.platform, is_affiliate=not args.organic, rules=cfg.rules)
        print("[OK] Pre-publish audit passed.")
        return 0
    except PrePostAuditError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    cfg = load_stack_config()
    client = TebarClient(config=cfg)
    thread_parts = [args.reply] if args.reply else None
    res = client.create_omnichannel_post(
        account_id=args.account_id,
        content=args.text,
        scheduled_at=args.at,
        format_type=args.format_type,
        reply_thread=thread_parts,
        bypass_pacing=args.bypass_pacing,
        is_affiliate=not args.organic,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


def _cmd_dedup(args: argparse.Namespace) -> int:
    cfg = load_stack_config()
    registry = cfg.data_dir / "video_fingerprint_registry.json"
    if args.register:
        rec = register_video_fingerprint(
            video_path=args.video,
            registry_path=registry,
            caption=args.caption,
            sku=args.sku,
            channel=args.channel,
        )
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0

    report = check_video_for_duplicate(
        video_path=args.video,
        registry_path=registry,
        caption=args.caption,
        sku=args.sku,
        channel=args.channel,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["is_duplicate"] else 0


def _cmd_fleet_health(args: argparse.Namespace) -> int:
    cfg = load_stack_config()
    manager = DeviceFleetManager(
        config_path=cfg.config_dir / "devices.json",
        locks_dir=cfg.data_dir / ".device_locks",
    )
    print(json.dumps(manager.run_fleet_healthcheck(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="money-stack",
        description=f"Modular Creator & Affiliate Automation Stack (Tebar scheduler: {TEBAR_REFERRAL_URL})",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Initialize local .env and config/*.json from examples")

    p_acc = sub.add_parser("accounts", help="List local account policies or live Tebar accounts")
    p_acc.add_argument("--live", action="store_true", help="Query live Tebar.app API")

    p_audit = sub.add_parser("audit", help="Run pre-publish linter on candidate text")
    p_audit.add_argument("--platform", default="threads")
    p_audit.add_argument("--text", nargs="+", required=True)
    p_audit.add_argument("--reply", default=None)
    p_audit.add_argument("--organic", action="store_true")

    p_sched = sub.add_parser("schedule", help="Validate and schedule a post via Tebar.app")
    p_sched.add_argument("--account-id", required=True)
    p_sched.add_argument("--text", required=True)
    p_sched.add_argument("--reply", default=None)
    p_sched.add_argument("--at", default=None, help="ISO-8601 timestamp")
    p_sched.add_argument("--format-type", default="CARD")
    p_sched.add_argument("--organic", action="store_true")
    p_sched.add_argument("--bypass-pacing", action="store_true")

    p_dedup = sub.add_parser("dedup", help="Check or register a video fingerprint")
    p_dedup.add_argument("video")
    p_dedup.add_argument("--caption", default="")
    p_dedup.add_argument("--sku", default=None)
    p_dedup.add_argument("--channel", default=None)
    p_dedup.add_argument("--register", action="store_true")

    sub.add_parser("fleet-health", help="Inspect connected physical ADB devices")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "setup": _cmd_setup,
        "accounts": _cmd_accounts,
        "audit": _cmd_audit,
        "schedule": _cmd_schedule,
        "dedup": _cmd_dedup,
        "fleet-health": _cmd_fleet_health,
    }
    try:
        return handlers[args.command](args)
    except TebarAuthError as exc:
        print(f"[AUTH] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
