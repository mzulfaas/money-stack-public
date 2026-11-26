"""Tests for pre-publish guardrails and SubID attribution utilities."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from money_stack.audit import (
    FastUrlVerifier,
    PrePostAuditError,
    PrePostErrorCode,
    assert_post_safe,
    generate_canonical_subid,
    inject_subid,
    lint_post_sequence,
    sanitize_links_in_text,
)


def test_generate_canonical_subid_wib_conversion():
    dt_utc = datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc)
    # 20:00 UTC + 7h = 2026-11-27 03:00 WIB -> 261127
    assert generate_canonical_subid("thr_tech", "reply", dt_utc, tz_offset_hours=7) == "THR_TECH_REPLY_261127"


def test_inject_subid_preserves_other_query_params_and_ignores_other_domains():
    dt = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
    updated = inject_subid(
        "https://s.shopee.co.id/AbCdEf12?foo=bar&sub_id=OLD",
        shortcode="IG_HOME",
        format_type="REEL",
        target_dt=dt,
    )
    assert "foo=bar" in updated
    assert "sub_id=IG_HOME_REEL_261126" in updated
    assert "OLD" not in updated

    unchanged = inject_subid("https://example.com/product?id=1", shortcode="IG_HOME")
    assert unchanged == "https://example.com/product?id=1"


def test_sanitize_links_in_text_keeps_trailing_punctuation():
    dt = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
    text = "Check this out: https://s.shopee.co.id/XyZ12345!"
    out = sanitize_links_in_text(text, shortcode="THR_TECH", format_type="REPLY", target_dt=dt)
    assert out == "Check this out: https://s.shopee.co.id/XyZ12345?sub_id=THR_TECH_REPLY_261126!"


def test_fast_url_verifier_caches_and_detects_dead_links(tmp_path: Path):
    cache_db = tmp_path / "url_cache.db"
    verifier = FastUrlVerifier(cache_db_path=cache_db)

    err = urllib.error.HTTPError(
        url="https://s.shopee.co.id/dead",
        code=302,
        msg="Found",
        hdrs={"Location": "https://shope.ee/error_page"},
        fp=None,
    )
    mock_opener = MagicMock()
    mock_opener.open.side_effect = err

    with patch("money_stack.audit.subid_resolver.urllib.request.build_opener", return_value=mock_opener):
        alive, code, loc = verifier.check_alive("https://s.shopee.co.id/dead")
        assert alive is False
        assert code == 302
        assert "error_page" in loc

        # Second call should hit SQLite WAL cache without reopening network
        mock_opener.open.reset_mock()
        alive_cached, code_cached, _ = verifier.check_alive("https://s.shopee.co.id/dead")
        assert alive_cached is False
        assert code_cached == 302
        mock_opener.open.assert_not_called()


def test_lint_post_sequence_barbell_and_slop_guards():
    # Clean 2-step barbell thread passes
    assert_post_safe(
        [
            "Desk cable trays solve 90% of visual clutter without drilling.",
            "Here is the exact clamp tray I tested: https://s.shopee.co.id/AbCd1234",
        ],
        platform="threads",
        is_affiliate=True,
    )

    # Violations: link in root, hashtag on threads, AI slop, broken URL, em-dash
    violations = lint_post_sequence(
        [
            "This game changer—check https://s.shopee.co.id/AbCd1234 #desksetup",
            "More detailshttp://insecure.example.com",
        ],
        platform="threads",
        is_affiliate=True,
    )
    codes = {v.error_code for v in violations}
    assert PrePostErrorCode.FORBIDDEN_SLOP_PHRASE in codes
    assert PrePostErrorCode.FORBIDDEN_PUNCTUATION in codes
    assert PrePostErrorCode.HASHTAG_FORBIDDEN in codes
    assert PrePostErrorCode.LINK_ISOLATION_VIOLATION in codes
    assert PrePostErrorCode.BROKEN_URL_TYPO in codes
    assert PrePostErrorCode.INSECURE_LINK_PROTOCOL in codes

    with pytest.raises(PrePostAuditError):
        assert_post_safe(["Organic post with link https://example.com"], platform="threads", is_affiliate=False)
