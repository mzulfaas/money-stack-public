"""Media analysis and 5-layer video/caption deduplication."""

from money_stack.media.video_dedup import (
    DuplicateContentError,
    assert_video_not_duplicate,
    check_video_for_duplicate,
    compute_dhash,
    compute_file_sha256,
    evaluate_video_similarity,
    hamming_distance,
    levenshtein_ratio,
    normalize_caption_text,
    register_video_fingerprint,
    token_jaccard_similarity,
)

__all__ = [
    "DuplicateContentError",
    "assert_video_not_duplicate",
    "check_video_for_duplicate",
    "compute_dhash",
    "compute_file_sha256",
    "evaluate_video_similarity",
    "hamming_distance",
    "levenshtein_ratio",
    "normalize_caption_text",
    "register_video_fingerprint",
    "token_jaccard_similarity",
]
