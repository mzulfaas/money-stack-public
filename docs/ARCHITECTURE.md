# Architecture Overview

`money-stack-public` separates **policy, scoring, and pre-publish verification** from **transport** (API scheduling via [Tebar.app](https://tebar.app/?ref=BLASTER), public feed polling, or physical Android ADB execution).

## 1. Creator & Affiliate Scheduler Flow

1. **Configuration (`money_stack.config`)**: Loads `config/accounts.json`, `config/personas.json`, `config/opportunities.json`, and `config/rules.json`. Account UUIDs, personas, shortcodes, daily caps, spacing intervals, blocked domains, and forbidden keywords live strictly in local config — never hardcoded in source.
2. **Pre-Publish Audit (`money_stack.audit`)**:
   - Enforces platform character boundaries, zero-hashtag constraints, and anti-AI-slop rules.
   - Enforces 2-step barbell link isolation (root posts stay link-free; final reply carries at most one `https://` link).
   - Verifies shortlink liveness without inflating click counters (`FastUrlVerifier` with SQLite WAL TTL cache).
   - Rewrites tracked shortlinks with bounded canonical SubIDs (`{SHORTCODE}_{FORMAT}_{YYMMDD}`).
3. **Pacing, Persona & Niche Firewall (`money_stack.tebar.PacingSubidGuard`)**:
   - Checks `blocked_via_scheduler`, `no_selling`, `blocked_domains`, account `forbidden_keywords`, and persona `forbidden_words`.
   - Fetches recent scheduled/published posts from Tebar to enforce `min_interval_m` and `daily_cap`.
4. **Submission & Ledger (`money_stack.tebar.TebarClient` + `money_stack.storage.fleet_db`)**:
   - Sends idempotent `POST /posts` to `https://api.tebar.app/v1`.
   - Logs `SCHEDULED` intent into `data/fleet_central.db` (WAL mode) with atomic task leases (`active_leases`).

## 2. Opportunity Radar & Freelance Tracker Flow

1. **Discovery (`money_stack.radar.opportunity_radar`)**: Polls GitHub Trending, Hugging Face Trending, and user-configured RSS/Atom job/bounty feeds (`config/opportunities.json`).
2. **Skill & Exclusion Scoring**: Ranks items against `skills` and drops items matching `excluded_keywords`.
3. **Deduplicated Pipeline (`money_stack.jobs.tracker`)**: Stores leads in the `opportunities` SQLite table keyed by `external_id`, tracks status transitions, and builds structured anti-slop proposal briefs tailored to the user's `PersonaProfile`.

## 3. Physical Device Runner (ADB Path)

For workflows that require native on-device composers:
- `ADBUIDriver` checks `dumpsys window` before every touch event and aborts (`ZERO_MISCLICK_ABORT`) if the device is on any launcher or kids-mode package.
- `DeviceFleetManager` coordinates multi-phone execution via `O_CREAT | O_EXCL` lock files with stale-lock recovery.
- `VisionOCRDriver` (`native/ocr_screen.swift`) extracts text coordinates in ~60–100ms on macOS without relying on Android accessibility dumps.
