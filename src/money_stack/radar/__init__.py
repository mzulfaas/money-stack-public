"""Opportunity and trend signal radar for creators, indie hackers, and freelancers."""

from money_stack.radar.opportunity_radar import (
    fetch_github_trending,
    fetch_huggingface_trending,
    fetch_rss_opportunities,
    parse_rss_or_atom,
    run_opportunity_radar,
    score_opportunity,
)

__all__ = [
    "fetch_github_trending",
    "fetch_huggingface_trending",
    "fetch_rss_opportunities",
    "parse_rss_or_atom",
    "run_opportunity_radar",
    "score_opportunity",
]
