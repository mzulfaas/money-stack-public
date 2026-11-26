"""SQLite WAL opportunity tracker and structured anti-slop proposal brief generator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from money_stack.config import PersonaProfile
from money_stack.storage.fleet_db import get_db_connection


VALID_OPPORTUNITY_STATUSES = {"NEW", "QUALIFIED", "PROPOSAL_DRAFTED", "APPLIED", "WON", "ARCHIVED"}


def init_opportunities_table(db_path: Path) -> None:
    """Initializes the opportunities table inside the shared SQLite WAL database."""
    with get_db_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'job',
                external_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT,
                score REAL NOT NULL DEFAULT 0.0,
                matched_skills_json TEXT,
                status TEXT NOT NULL DEFAULT 'NEW',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_opp_status_score
            ON opportunities(status, score DESC);
            """
        )


def upsert_opportunity(db_path: Path, item: Dict[str, Any]) -> int:
    """Inserts or updates an opportunity keyed by external_id; avoids duplicate outreach."""
    init_opportunities_table(db_path)
    now = datetime.now(timezone.utc).isoformat()
    ext_id = str(item.get("external_id") or item.get("url") or item.get("title") or "").strip()
    if not ext_id:
        raise ValueError("Opportunity must include external_id, url, or title.")

    skills_json = json.dumps(item.get("matched_skills", []), ensure_ascii=False)
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO opportunities (
                source, kind, external_id, title, url, description,
                score, matched_skills_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                score=MAX(opportunities.score, excluded.score),
                matched_skills_json=excluded.matched_skills_json,
                updated_at=excluded.updated_at
            """,
            (
                str(item.get("source", "unknown")),
                str(item.get("kind", "job")),
                ext_id,
                str(item.get("title", "")),
                str(item.get("url", "")),
                str(item.get("description", "")),
                float(item.get("score", 0.0)),
                skills_json,
                "NEW",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT id FROM opportunities WHERE external_id = ?", (ext_id,)).fetchone()
        return int(row["id"])


def list_opportunities(
    db_path: Path,
    status: Optional[str] = None,
    min_score: float = 0.0,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Lists tracked opportunities filtered by status and minimum score."""
    if not db_path.exists():
        return []
    init_opportunities_table(db_path)
    clauses = ["score >= ?"]
    params: List[Any] = [min_score]
    if status:
        clauses.append("status = ?")
        params.append(status.strip().upper())
    params.append(limit)
    sql = f"SELECT * FROM opportunities WHERE {' AND '.join(clauses)} ORDER BY score DESC, id DESC LIMIT ?"
    with get_db_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["matched_skills"] = json.loads(d.pop("matched_skills_json") or "[]")
            results.append(d)
        return results


def update_opportunity_status(db_path: Path, opp_id: int, status: str) -> bool:
    """Transitions an opportunity to a new workflow status."""
    norm = status.strip().upper()
    if norm not in VALID_OPPORTUNITY_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Allowed: {sorted(VALID_OPPORTUNITY_STATUSES)}")
    init_opportunities_table(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE opportunities SET status = ?, updated_at = ? WHERE id = ?",
            (norm, now, opp_id),
        )
        return cur.rowcount > 0


def build_proposal_brief(
    opportunity: Dict[str, Any],
    persona: Optional[PersonaProfile] = None,
    proof_links: Sequence[str] = (),
) -> str:
    """Builds a concise, non-generic proposal brief tailored to the user's persona."""
    title = str(opportunity.get("title", "Untitled Project")).strip()
    skills = opportunity.get("matched_skills") or []
    skill_line = ", ".join(skills) if skills else "your core requirements"
    archetype = persona.archetype if persona and persona.archetype else "Automation & Software Engineer"
    cadence = persona.cadence if persona and persona.cadence else "Direct, concise, evidence-first"

    lines = [
        f"Subject / Hook: Relevant implementation experience for {title}",
        f"Persona Lens: {archetype} ({cadence})",
        "",
        f"1. Direct Fit: I work directly with {skill_line}.",
        "2. Proposed First Milestone: Deliver a working minimal slice + reproducible verification test before scaling.",
    ]
    if proof_links:
        lines.append("3. Relevant Public Proof:")
        for link in proof_links:
            lines.append(f"   - {link}")
    else:
        lines.append("3. Relevant Public Proof: Attach 1-2 matching GitHub repo links from your portfolio.")

    brief = "\n".join(lines)
    if persona and persona.forbidden_words:
        lower = brief.lower()
        for word in persona.forbidden_words:
            if word in lower:
                raise ValueError(f"Draft violates persona forbidden word: '{word}'")
    return brief
