"""Public feed scanner for AI trends, remote jobs, and freelance/bounty opportunities."""

from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


FetcherFn = Callable[[str, Dict[str, str], int], str]


def _default_http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 12) -> str:
    req_headers = {"User-Agent": "MoneyStackRadar/0.1"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()


def parse_rss_or_atom(xml_text: str, source_name: str = "rss") -> List[Dict[str, Any]]:
    """Parses RSS 2.0 or Atom feeds into normalized opportunity dicts."""
    if not xml_text or not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    items: List[Dict[str, Any]] = []

    # RSS 2.0: channel/item
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description") or "")
        pub_date = (item.findtext("pubDate") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        if title or link:
            items.append(
                {
                    "source": source_name,
                    "kind": "job",
                    "external_id": guid,
                    "title": title,
                    "url": link,
                    "description": desc[:600],
                    "published_at": pub_date,
                }
            )

    if items:
        return items

    # Atom: {http://www.w3.org/2005/Atom}entry or unqualified entry
    ns = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f".//{ns}entry") or root.findall(".//entry")
    for entry in entries:
        title = (entry.findtext(f"{ns}title") or entry.findtext("title") or "").strip()
        link_el = entry.find(f"{ns}link")
        if link_el is None:
            link_el = entry.find("link")
        link = (link_el.attrib.get("href", "") if link_el is not None else "").strip()
        summary = _strip_html(
            entry.findtext(f"{ns}summary")
            or entry.findtext(f"{ns}content")
            or entry.findtext("summary")
            or ""
        )
        entry_id = (entry.findtext(f"{ns}id") or entry.findtext("id") or link or title).strip()
        updated = (entry.findtext(f"{ns}updated") or entry.findtext("updated") or "").strip()
        if title or link:
            items.append(
                {
                    "source": source_name,
                    "kind": "job",
                    "external_id": entry_id,
                    "title": title,
                    "url": link,
                    "description": summary[:600],
                    "published_at": updated,
                }
            )
    return items


def fetch_rss_opportunities(
    feeds: Sequence[Dict[str, str]],
    fetcher: Optional[FetcherFn] = None,
) -> List[Dict[str, Any]]:
    """Fetches and parses configured RSS/Atom job or bounty feeds."""
    http_get = fetcher or _default_http_get
    results: List[Dict[str, Any]] = []
    for feed in feeds:
        url = str(feed.get("url", "")).strip()
        name = str(feed.get("name", url or "rss"))
        if not url:
            continue
        try:
            body = http_get(url, {}, 12)
            results.extend(parse_rss_or_atom(body, source_name=name))
        except Exception:
            continue
    return results


def fetch_github_trending(
    topic: str = "ai",
    limit: int = 10,
    min_stars: int = 50,
    lookback_days: int = 14,
    fetcher: Optional[FetcherFn] = None,
) -> List[Dict[str, Any]]:
    """Fetches fast-growing GitHub repositories for content/tool signal mining."""
    http_get = fetcher or _default_http_get
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    query = f"stars:>{min_stars}+created:>{since}+topic:{topic}"
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit}"
    try:
        raw = http_get(url, {"Accept": "application/vnd.github.v3+json"}, 12)
        payload = json.loads(raw)
    except Exception:
        return []

    items: List[Dict[str, Any]] = []
    for repo in payload.get("items", []):
        items.append(
            {
                "source": "github",
                "kind": "trend",
                "external_id": repo.get("full_name") or repo.get("html_url"),
                "title": repo.get("full_name") or repo.get("name", ""),
                "url": repo.get("html_url", ""),
                "description": (repo.get("description") or "")[:400],
                "stars": int(repo.get("stargazers_count", 0) or 0),
                "language": repo.get("language") or "",
                "published_at": repo.get("created_at") or "",
            }
        )
    return items


def fetch_huggingface_trending(
    limit: int = 10,
    fetcher: Optional[FetcherFn] = None,
) -> List[Dict[str, Any]]:
    """Fetches trending models from Hugging Face for AI content/tool ideas."""
    http_get = fetcher or _default_http_get
    url = f"https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit={limit}"
    try:
        raw = http_get(url, {}, 12)
        data = json.loads(raw)
    except Exception:
        return []

    items: List[Dict[str, Any]] = []
    for model in data if isinstance(data, list) else []:
        model_id = str(model.get("id", ""))
        if not model_id:
            continue
        items.append(
            {
                "source": "huggingface",
                "kind": "trend",
                "external_id": model_id,
                "title": model_id,
                "url": f"https://huggingface.co/{model_id}",
                "description": str(model.get("pipeline_tag") or "model"),
                "likes": int(model.get("likes", 0) or 0),
                "trending_score": float(model.get("trendingScore", 0) or 0),
            }
        )
    return items


def score_opportunity(
    item: Dict[str, Any],
    skills: Sequence[str] = (),
    excluded_keywords: Sequence[str] = (),
) -> Dict[str, Any]:
    """Scores an opportunity or trend signal against user-defined skills and exclusions."""
    haystack = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("description", "")),
            str(item.get("language", "")),
        ]
    ).lower()

    for bad in excluded_keywords:
        if bad.lower() in haystack:
            enriched = dict(item)
            enriched["score"] = 0.0
            enriched["matched_skills"] = []
            enriched["excluded_reason"] = f"matched excluded keyword '{bad}'"
            return enriched

    matched = [s for s in skills if s.lower() in haystack]
    if item.get("kind") == "trend":
        if item.get("source") == "github":
            stars = int(item.get("stars", 0))
            base = 85.0 + min(15.0, stars / 200.0) if 100 <= stars <= 3000 else min(80.0, float(stars))
        elif item.get("source") == "huggingface":
            base = min(95.0, float(item.get("trending_score", 0)) * 2.0 + float(item.get("likes", 0)) * 0.5)
        else:
            base = 50.0
        score = min(100.0, base + len(matched) * 5.0)
    else:
        # Job / bounty scoring: base 25 + 20 per matched skill, capped at 100
        score = min(100.0, (25.0 if matched else 5.0) + len(matched) * 20.0)

    enriched = dict(item)
    enriched["score"] = round(score, 2)
    enriched["matched_skills"] = matched
    return enriched


def run_opportunity_radar(
    mode: str = "all",
    skills: Sequence[str] = (),
    excluded_keywords: Sequence[str] = (),
    rss_feeds: Sequence[Dict[str, str]] = (),
    limit: int = 10,
    output_path: Optional[Path] = None,
    fetcher: Optional[FetcherFn] = None,
) -> Dict[str, Any]:
    """Runs trend and/or job feed discovery, scores results, and optionally saves JSON."""
    raw_items: List[Dict[str, Any]] = []
    if mode in ("trends", "all"):
        raw_items.extend(fetch_github_trending(limit=limit, fetcher=fetcher))
        raw_items.extend(fetch_huggingface_trending(limit=limit, fetcher=fetcher))
    if mode in ("jobs", "all") and rss_feeds:
        raw_items.extend(fetch_rss_opportunities(rss_feeds, fetcher=fetcher))

    scored = [
        score_opportunity(item, skills=skills, excluded_keywords=excluded_keywords)
        for item in raw_items
    ]
    scored = [item for item in scored if item.get("score", 0.0) > 0.0]
    scored.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "total": len(scored),
        "items": scored,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
