"""Freelance & client opportunity SQLite tracker and anti-slop proposal brief builder."""

from money_stack.jobs.tracker import (
    build_proposal_brief,
    init_opportunities_table,
    list_opportunities,
    update_opportunity_status,
    upsert_opportunity,
)

__all__ = [
    "build_proposal_brief",
    "init_opportunities_table",
    "list_opportunities",
    "update_opportunity_status",
    "upsert_opportunity",
]
