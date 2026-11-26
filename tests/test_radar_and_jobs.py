"""Tests for opportunity radar, RSS/Atom parsing, and freelance opportunity tracker."""

import json
from pathlib import Path

import pytest

from money_stack.config import PersonaProfile
from money_stack.jobs import (
    build_proposal_brief,
    list_opportunities,
    update_opportunity_status,
    upsert_opportunity,
)
from money_stack.radar import parse_rss_or_atom, run_opportunity_radar, score_opportunity


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Remote Jobs</title>
    <item>
      <title>Senior Python Automation &amp; Scraping Engineer</title>
      <link>https://jobs.example.com/101</link>
      <guid>job-101</guid>
      <description><![CDATA[<p>Build Playwright and Python scrapers with anti-bot retries.</p>]]></description>
      <pubDate>Thu, 26 Nov 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Unpaid Volunteer Social Moderator</title>
      <link>https://jobs.example.com/102</link>
      <guid>job-102</guid>
      <description>Volunteer role only.</description>
    </item>
  </channel>
</rss>
"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>atom-1</id>
    <title>Flutter Invoice Mobile App Contract</title>
    <link href="https://jobs.example.com/atom-1" />
    <summary>Offline-first Flutter app development.</summary>
    <updated>2026-11-26T01:00:00Z</updated>
  </entry>
</feed>
"""


def test_parse_rss_and_atom_feeds():
    rss_items = parse_rss_or_atom(RSS_SAMPLE, source_name="test_rss")
    assert len(rss_items) == 2
    assert rss_items[0]["external_id"] == "job-101"
    assert "Playwright" in rss_items[0]["description"]

    atom_items = parse_rss_or_atom(ATOM_SAMPLE, source_name="test_atom")
    assert len(atom_items) == 1
    assert atom_items[0]["url"] == "https://jobs.example.com/atom-1"


def test_score_and_run_opportunity_radar_with_mock_fetcher(tmp_path: Path):
    def fake_fetcher(url: str, headers: dict, timeout: int) -> str:
        if "api.github.com" in url:
            return json.dumps(
                {
                    "items": [
                        {
                            "full_name": "org/python-auto-agent",
                            "html_url": "https://github.com/org/python-auto-agent",
                            "description": "Python automation toolkit",
                            "stargazers_count": 400,
                            "language": "Python",
                        }
                    ]
                }
            )
        if "huggingface.co" in url:
            return json.dumps([{"id": "org/small-tts", "pipeline_tag": "text-to-speech", "likes": 40, "trendingScore": 25}])
        return RSS_SAMPLE

    out_file = tmp_path / "radar" / "latest.json"
    result = run_opportunity_radar(
        mode="all",
        skills=["python", "scraping", "playwright", "automation"],
        excluded_keywords=["unpaid", "volunteer"],
        rss_feeds=[{"name": "remote", "url": "https://jobs.example.com/feed.rss"}],
        output_path=out_file,
        fetcher=fake_fetcher,
    )

    assert out_file.is_file()
    titles = [item["title"] for item in result["items"]]
    assert "Unpaid Volunteer Social Moderator" not in titles
    assert "Senior Python Automation & Scraping Engineer" in titles
    assert "org/python-auto-agent" in titles
    assert score_opportunity({"title": "Python scraping", "kind": "job"}, skills=["python", "scraping"])["score"] == 65.0


def test_opportunity_tracker_dedup_status_and_proposal_brief(tmp_path: Path):
    db_path = tmp_path / "fleet.db"
    item = {
        "source": "remote_rss",
        "kind": "job",
        "external_id": "job-101",
        "title": "Python Scraping Pipeline",
        "url": "https://jobs.example.com/101",
        "description": "Need clean Playwright extractor.",
        "score": 85.0,
        "matched_skills": ["python", "scraping"],
    }
    opp_id_1 = upsert_opportunity(db_path, item)
    opp_id_2 = upsert_opportunity(db_path, {**item, "score": 90.0})
    assert opp_id_1 == opp_id_2

    rows = list_opportunities(db_path, min_score=80.0)
    assert len(rows) == 1
    assert rows[0]["score"] == 90.0

    assert update_opportunity_status(db_path, opp_id_1, "PROPOSAL_DRAFTED") is True
    assert list_opportunities(db_path, status="PROPOSAL_DRAFTED")[0]["id"] == opp_id_1

    persona = PersonaProfile(name="builder", archetype="Systems Builder", forbidden_words=("synergy",))
    brief = build_proposal_brief(
        rows[0],
        persona=persona,
        proof_links=["https://github.com/mzulfaas/python-scraper-anti-bot-boilerplate"],
    )
    assert "Python Scraping Pipeline" in brief
    assert "python-scraper-anti-bot-boilerplate" in brief
