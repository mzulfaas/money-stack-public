"""Tests for SQLite WAL FleetDB and 5-layer video/caption deduplication."""

from pathlib import Path
from unittest.mock import patch

import pytest

from money_stack.media.video_dedup import (
    DuplicateContentError,
    assert_video_not_duplicate,
    evaluate_video_similarity,
    hamming_distance,
    levenshtein_ratio,
    normalize_caption_text,
    register_video_fingerprint,
    token_jaccard_similarity,
)
from money_stack.storage.fleet_db import (
    acquire_lease,
    has_recent_publication,
    record_publication,
    release_lease,
)


def test_fleet_db_publications_and_atomic_leases(tmp_path: Path):
    db_path = tmp_path / "fleet.db"
    assert has_recent_publication(db_path, "SKU-1", "threads") is False

    row_id = record_publication(
        db_path=db_path,
        sku="SKU-1",
        platform="threads",
        account_handle="@tech_creator_example",
        root_text="Short desk tour notes.",
    )
    assert row_id == 1
    assert has_recent_publication(db_path, "SKU-1", "threads") is True
    assert has_recent_publication(db_path, "SKU-1", "instagram") is False

    lease_1 = acquire_lease(db_path, "SKU-1:threads", "threads", "@tech_creator_example", worker_pid=111)
    assert lease_1 is not None
    # Contending worker cannot acquire active lease
    assert acquire_lease(db_path, "SKU-1:threads", "threads", "@tech_creator_example", worker_pid=222) is None
    assert release_lease(db_path, lease_1) is True
    # Released lease can be re-acquired
    lease_2 = acquire_lease(db_path, "SKU-1:threads", "threads", "@tech_creator_example", worker_pid=222)
    assert lease_2 is not None


def test_text_normalization_and_similarity_metrics():
    assert normalize_caption_text("Check @user #tag https://example.com Now!") == "check now"
    assert levenshtein_ratio("desk lamp review", "desk lamp review") == 1.0
    assert levenshtein_ratio("desk lamp", "chair mat") < 0.4
    assert token_jaccard_similarity("desk lamp usb", "usb desk lamp") == 1.0
    assert hamming_distance("ffffffffffffffff", "fffffffffffffffe") == 1


def test_evaluate_video_similarity_blocks_and_passes():
    base = {
        "sha256": "aaa",
        "dhashes": ["0000000000000000"] * 5,
        "has_audio": True,
        "audio_rms": [-18.0, -18.0, -18.0, -18.0],
        "norm_caption": "minimalist monitor light bar setup",
        "duration_s": 15.0,
    }

    # Exact SHA256 match
    _, verdict_l1, triggers_l1 = evaluate_video_similarity(dict(base), dict(base))
    assert verdict_l1 == "BLOCK"
    assert "L1_EXACT_SHA256_MATCH" in triggers_l1

    # Distinct video & caption passes
    distinct = {
        "sha256": "bbb",
        "dhashes": ["ffffffffffffffff"] * 5,
        "has_audio": True,
        "audio_rms": [-45.0, -45.0, -45.0, -45.0],
        "norm_caption": "coffee grinder burr cleaning tutorial",
        "duration_s": 28.0,
    }
    score_ok, verdict_ok, _ = evaluate_video_similarity(distinct, base)
    assert verdict_ok == "PASS"
    assert score_ok < 65.0


def test_video_dedup_registry_sku_cooldown(tmp_path: Path):
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"fake-video-bytes-v1")
    registry_path = tmp_path / "fingerprints.json"

    fake_meta = {"duration_s": 12.0, "bit_rate": 1000, "size_bytes": 20, "resolution": "1080x1920", "has_audio": False}
    with (
        patch("money_stack.media.video_dedup.probe_video_metadata", return_value=fake_meta),
        patch("money_stack.media.video_dedup.extract_perceptual_keyframes_dhash", return_value=["1111111111111111"] * 5),
        patch("money_stack.media.video_dedup.extract_audio_signature", return_value={"has_audio": False, "rms_profile": []}),
    ):
        register_video_fingerprint(video_file, registry_path, caption="Desk organizer", sku="SKU-42", channel="reels")

        video_file_2 = tmp_path / "clip2.mp4"
        video_file_2.write_bytes(b"different-bytes-v2")
        with pytest.raises(DuplicateContentError, match="L5_SKU_COOLDOWN_ACTIVE"):
            assert_video_not_duplicate(
                video_file_2,
                registry_path=registry_path,
                caption="Completely different caption",
                sku="SKU-42",
                channel="reels",
            )
