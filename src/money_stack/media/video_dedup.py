"""5-layer video and caption duplicate detection engine."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class DuplicateContentError(RuntimeError):
    """Raised when a video or caption matches an existing published asset."""


def load_fingerprint_registry(registry_path: Path) -> List[Dict[str, Any]]:
    if not registry_path.is_file():
        return []
    try:
        with registry_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("records", [])
        return records if isinstance(records, list) else []
    except Exception:
        return []


def save_fingerprint_registry(registry_path: Path, records: List[Dict[str, Any]]) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_records": len(records),
        "records": records,
    }
    with registry_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def compute_file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video_metadata(file_path: Path) -> Dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate,size:stream=width,height,codec_type",
        "-of",
        "json",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise ValueError(f"ffprobe failed for {file_path}: {res.stderr.strip()}")

    data = json.loads(res.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    duration_s = float(fmt.get("duration", 0.0) or 0.0)
    bit_rate = int(fmt.get("bit_rate", 0) or 0)
    size_bytes = int(fmt.get("size", file_path.stat().st_size))

    width = 0
    height = 0
    has_audio = False
    for stream in streams:
        if stream.get("codec_type") == "video" and not width:
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)
        elif stream.get("codec_type") == "audio":
            has_audio = True

    return {
        "duration_s": duration_s,
        "duration_ms": int(duration_s * 1000),
        "bit_rate": bit_rate,
        "size_bytes": size_bytes,
        "resolution": f"{width}x{height}",
        "has_audio": has_audio,
    }


def compute_dhash(image: Any, hash_size: int = 8) -> str:
    """Computes a 64-bit difference hash from a PIL Image."""
    from PIL import Image  # optional media dependency

    resized = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(resized.getdata())
    width = hash_size + 1
    bits = []
    for row in range(hash_size):
        for col in range(hash_size):
            bits.append(1 if pixels[row * width + col] > pixels[row * width + col + 1] else 0)
    val = 0
    for bit in bits:
        val = (val << 1) | bit
    return f"{val:016x}"


def hamming_distance(hex1: str, hex2: str) -> int:
    if not hex1 or not hex2 or len(hex1) != 16 or len(hex2) != 16:
        return 64
    return bin(int(hex1, 16) ^ int(hex2, 16)).count("1")


def extract_perceptual_keyframes_dhash(file_path: Path, duration_s: float) -> List[str]:
    from PIL import Image

    safe_dur = duration_s if duration_s > 0 else 10.0
    percentages = (0.10, 0.30, 0.50, 0.70, 0.90)
    hashes: List[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, pct in enumerate(percentages):
            target = max(0.2, min(safe_dur - 0.2, safe_dur * pct))
            frame_path = Path(tmpdir) / f"frame_{idx}.jpg"
            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-ss",
                f"{target:.2f}",
                "-i",
                str(file_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ]
            subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if frame_path.is_file():
                try:
                    with Image.open(frame_path) as img:
                        hashes.append(compute_dhash(img))
                    continue
                except Exception:
                    pass
            hashes.append("0000000000000000")
    return hashes


def extract_audio_signature(file_path: Path, has_audio: bool) -> Dict[str, Any]:
    if not has_audio:
        return {"has_audio": False, "rms_profile": []}
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(file_path),
        "-af",
        "astats=metadata=1:reset=1",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    matches = re.findall(r"RMS level dB:\s*([-\d\.]+)", res.stderr or res.stdout)
    return {"has_audio": True, "rms_profile": [float(x) for x in matches[:4]]}


def normalize_caption_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.lower()
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"[@#]\w+", "", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def levenshtein_ratio(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    len1, len2 = len(s1), len(s2)
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return 1.0 - (dp[len1][len2] / max(len1, len2))


def token_jaccard_similarity(s1: str, s2: str) -> float:
    t1, t2 = set(s1.split()), set(s2.split())
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


def evaluate_video_similarity(
    candidate: Dict[str, Any],
    existing: Dict[str, Any],
) -> Tuple[float, str, List[str]]:
    """Evaluates composite similarity score (0..100) and verdict (PASS/REVIEW/BLOCK)."""
    triggers: List[str] = []
    if candidate.get("sha256") and candidate["sha256"] == existing.get("sha256"):
        return 100.0, "BLOCK", ["L1_EXACT_SHA256_MATCH"]

    cand_hashes = candidate.get("dhashes", [])
    exist_hashes = existing.get("dhashes", [])
    if len(cand_hashes) == 5 and len(exist_hashes) == 5:
        distances = sorted(hamming_distance(a, b) for a, b in zip(cand_hashes, exist_hashes))
        median_dist = distances[len(distances) // 2]
    else:
        median_dist = 64

    visual_sim = max(0.0, 1.0 - (median_dist / 32.0))
    if median_dist <= 4:
        triggers.append(f"L2_PERCEPTUAL_NEAR_IDENTICAL (median_hamming={median_dist})")
    elif median_dist <= 10:
        triggers.append(f"L2_PERCEPTUAL_STRONG_SIMILARITY (median_hamming={median_dist})")

    if candidate.get("has_audio") and existing.get("has_audio"):
        c_rms, e_rms = candidate.get("audio_rms", []), existing.get("audio_rms", [])
        if c_rms and e_rms and len(c_rms) == len(e_rms):
            avg_diff = sum(abs(a - b) for a, b in zip(c_rms, e_rms)) / len(c_rms)
            audio_sim = max(0.0, 1.0 - (avg_diff / 20.0))
        else:
            audio_sim = 0.5
    else:
        audio_sim = 0.5

    c1, c2 = candidate.get("norm_caption", ""), existing.get("norm_caption", "")
    lev = levenshtein_ratio(c1, c2)
    jacc = token_jaccard_similarity(c1, c2)
    caption_sim = max(lev, jacc)
    if lev >= 0.85:
        triggers.append(f"L4_CAPTION_PARAPHRASE (lev={lev:.2f})")
    elif jacc >= 0.70:
        triggers.append(f"L4_CAPTION_JACCARD_OVERLAP (jacc={jacc:.2f})")

    dur_diff = abs(float(candidate.get("duration_s", 0.0)) - float(existing.get("duration_s", 0.0)))
    metadata_sim = 1.0 if dur_diff <= 0.3 else max(0.0, 1.0 - (dur_diff / 5.0))

    composite = 100.0 * (
        0.35 * visual_sim + 0.30 * audio_sim + 0.20 * caption_sim + 0.15 * metadata_sim
    )

    if median_dist <= 4:
        return max(composite, 95.0), "BLOCK", triggers
    if lev >= 0.85 and (median_dist <= 12 or dur_diff <= 0.5):
        return max(composite, 92.0), "BLOCK", triggers

    if composite >= 85.0:
        verdict = "BLOCK"
    elif composite >= 65.0 or triggers:
        verdict = "REVIEW"
    else:
        verdict = "PASS"
    return composite, verdict, triggers


def _build_candidate(video_path: Path, caption: str, sku: Optional[str], channel: Optional[str]) -> Dict[str, Any]:
    meta = probe_video_metadata(video_path)
    sha256 = compute_file_sha256(video_path)
    dhashes = extract_perceptual_keyframes_dhash(video_path, meta["duration_s"])
    audio_sig = extract_audio_signature(video_path, meta["has_audio"])
    return {
        "file_name": video_path.name,
        "sha256": sha256,
        "duration_s": meta["duration_s"],
        "bit_rate": meta["bit_rate"],
        "resolution": meta["resolution"],
        "dhashes": dhashes,
        "has_audio": meta["has_audio"],
        "audio_rms": audio_sig.get("rms_profile", []),
        "raw_caption": caption,
        "norm_caption": normalize_caption_text(caption),
        "sku": str(sku) if sku else None,
        "channel": channel,
    }


def check_video_for_duplicate(
    video_path: Union[str, Path],
    registry_path: Path,
    caption: str = "",
    sku: Optional[str] = None,
    channel: Optional[str] = None,
    cooldown_days: int = 30,
) -> Dict[str, Any]:
    p = Path(video_path)
    if not p.is_file():
        raise FileNotFoundError(f"Video file not found: {p}")

    candidate = _build_candidate(p, caption, sku, channel)
    registry = load_fingerprint_registry(registry_path)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    highest_score = 0.0
    highest_match: Optional[Dict[str, Any]] = None
    final_verdict = "PASS"
    hits: List[str] = []

    for item in registry:
        created_at = item.get("created_at")
        if created_at:
            try:
                dt_item = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if (now_utc - dt_item).total_seconds() > cooldown_days * 86400:
                    continue
            except ValueError:
                pass

        if sku and item.get("sku") == str(sku) and channel and item.get("channel") == channel:
            hits.append(f"L5_SKU_COOLDOWN_ACTIVE: SKU {sku} already published on {channel}")
            final_verdict = "BLOCK"
            highest_score = 100.0
            highest_match = item
            break

        score, verdict, triggers = evaluate_video_similarity(candidate, item)
        if score > highest_score:
            highest_score = score
            highest_match = item
            hits.extend(triggers)
            if verdict == "BLOCK":
                final_verdict = "BLOCK"
                break
            if verdict == "REVIEW" and final_verdict != "BLOCK":
                final_verdict = "REVIEW"

    return {
        "is_duplicate": final_verdict in ("BLOCK", "REVIEW"),
        "verdict": final_verdict,
        "composite_score": round(highest_score, 1),
        "triggers": sorted(set(hits)),
        "matched_entry": highest_match.get("video_id") if highest_match else None,
        "matched_file": highest_match.get("file_name") if highest_match else None,
        "candidate": candidate,
    }


def register_video_fingerprint(
    video_path: Union[str, Path],
    registry_path: Path,
    caption: str = "",
    sku: Optional[str] = None,
    channel: Optional[str] = None,
    video_id: Optional[str] = None,
) -> Dict[str, Any]:
    p = Path(video_path)
    if not p.is_file():
        raise FileNotFoundError(f"Video file not found: {p}")

    record = _build_candidate(p, caption, sku, channel)
    rec_id = video_id or (
        f"vid_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}_{record['sha256'][:8]}"
    )
    record["video_id"] = rec_id
    record["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    registry = load_fingerprint_registry(registry_path)
    filtered = [r for r in registry if r.get("sha256") != record["sha256"] and r.get("video_id") != rec_id]
    filtered.append(record)
    save_fingerprint_registry(registry_path, filtered)
    return record


def assert_video_not_duplicate(
    video_path: Union[str, Path],
    registry_path: Path,
    caption: str = "",
    sku: Optional[str] = None,
    channel: Optional[str] = None,
    register_if_clean: bool = True,
    cooldown_days: int = 30,
) -> Dict[str, Any]:
    report = check_video_for_duplicate(
        video_path=video_path,
        registry_path=registry_path,
        caption=caption,
        sku=sku,
        channel=channel,
        cooldown_days=cooldown_days,
    )
    if report["is_duplicate"] or report["verdict"] == "BLOCK":
        reasons = "; ".join(report["triggers"]) or f"Composite score {report['composite_score']}%"
        raise DuplicateContentError(
            f"Duplicate detected for '{Path(video_path).name}' ({report['verdict']}): {reasons}"
        )
    if register_if_clean:
        register_video_fingerprint(
            video_path=video_path,
            registry_path=registry_path,
            caption=caption,
            sku=sku,
            channel=channel,
        )
    return report
