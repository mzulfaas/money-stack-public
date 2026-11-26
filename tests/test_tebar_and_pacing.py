"""Tests for Tebar REST client, pacing guardrails, and account firewall policies."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from money_stack import TEBAR_REFERRAL_URL
from money_stack.config import AccountPolicy, StackConfig
from money_stack.storage.fleet_db import get_db_connection
from money_stack.tebar import FatalPacingViolation, PacingSubidGuard, TebarAuthError, TebarClient


def _sample_config(tmp_path: Path) -> StackConfig:
    accounts = {
        "acc-threads": AccountPolicy(
            account_id="acc-threads",
            platform="threads",
            handle="@tech_creator_example",
            shortcode="THR_TECH",
            daily_cap=2,
            min_interval_m=120,
            language="en",
            blocked_domains=("amazon.com",),
            forbidden_keywords=("gambling",),
        ),
        "acc-editorial": AccountPolicy(
            account_id="acc-editorial",
            platform="instagram",
            handle="@pure_editorial_example",
            shortcode="IG_EDIT",
            no_selling=True,
        ),
        "acc-tiktok": AccountPolicy(
            account_id="acc-tiktok",
            platform="tiktok",
            handle="@shop_example",
            shortcode="TT_SHOP",
            blocked_via_scheduler=True,
            blocked_reason="Use physical ADB composer for yellow cart.",
        ),
    }
    return StackConfig(
        root_dir=tmp_path,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        accounts=accounts,
    )


def test_tebar_client_requires_api_key_with_referral_link(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TEBAR_API_KEY", raising=False)
    with pytest.raises(TebarAuthError) as exc_info:
        TebarClient(config=_sample_config(tmp_path))
    assert TEBAR_REFERRAL_URL in str(exc_info.value)


def test_pacing_guard_blocks_policy_and_spacing_violations(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    now = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
    existing_posts = [
        {"id": "p1", "status": "scheduled", "scheduled_at": (now - timedelta(minutes=30)).isoformat()},
    ]
    guard = PacingSubidGuard(config=cfg, posts_fetcher=lambda _: existing_posts)

    # Blocked via scheduler
    with pytest.raises(FatalPacingViolation, match="SCHEDULER_BLOCKED"):
        guard.validate_and_sanitize("acc-tiktok", "Product showcase clip")

    # No-selling policy
    with pytest.raises(FatalPacingViolation, match="NO_SELLING_POLICY"):
        guard.validate_and_sanitize("acc-editorial", "Check https://s.shopee.co.id/AbCd1234")

    # Blocked domain
    with pytest.raises(FatalPacingViolation, match="BLOCKED_DOMAIN"):
        guard.validate_and_sanitize("acc-threads", "Root text", reply_thread=["https://amazon.com/dp/B000"])

    # Forbidden keyword
    with pytest.raises(FatalPacingViolation, match="NICHE_FIREWALL"):
        guard.validate_and_sanitize("acc-threads", "Best gambling site", is_affiliate=False)

    # Pacing violation (30m < 120m)
    with pytest.raises(FatalPacingViolation, match="PACING_VIOLATION"):
        guard.validate_and_sanitize(
            "acc-threads",
            "Clean engineering thread root.",
            scheduled_at=now.isoformat(),
            is_affiliate=False,
        )


def test_tebar_client_schedules_threads_post_with_subid_and_records_db(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    db_path = tmp_path / "data" / "fleet.db"
    guard = PacingSubidGuard(config=cfg, posts_fetcher=lambda _: [])
    client = TebarClient(api_key="test-key-123", config=cfg, guard=guard, db_path=db_path)

    captured = {}

    def _fake_request(endpoint, method="GET", data=None, idempotency_key=None, timeout=15):
        captured["endpoint"] = endpoint
        captured["method"] = method
        captured["data"] = data
        return {"id": "tebar-post-99", "status": "scheduled"}

    with patch.object(client, "_request", side_effect=_fake_request):
        res = client.create_threads_post(
            account_id="acc-threads",
            content="Clean keyboard desk setup notes without clutter.",
            topic_tag="#DeskSetup",
            thread_parts=["Tested bracket here: https://s.shopee.co.id/AbCd1234"],
            scheduled_at="2026-11-26T12:00:00+00:00",
            publication_record={"sku": "SKU-1001"},
        )

    assert res["id"] == "tebar-post-99"
    assert captured["endpoint"] == "/posts"
    target_opts = captured["data"]["targets"][0]["options"]
    assert target_opts["topic_tag"] == "DeskSetup"
    assert "sub_id=THR_TECH_REPLY_261126" in target_opts["thread"][0]

    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT sku, status, platform FROM publications").fetchall()
        assert len(rows) == 1
        assert dict(rows[0]) == {"sku": "SKU-1001", "status": "SCHEDULED", "platform": "threads"}
