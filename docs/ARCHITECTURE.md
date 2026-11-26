# Architecture Overview

`money-stack-public` separates **policy & pre-publish verification** from **transport** (API scheduling via [Tebar.app](https://tebar.app/?ref=BLASTER) or physical Android ADB execution).

## Request Flow (Scheduler Path)

1. **Configuration (`money_stack.config`)**: Loads `config/accounts.json` and `config/rules.json`. Account UUIDs, shortcodes, daily caps, spacing intervals, blocked domains, and forbidden keywords live strictly in local config — never hardcoded in source.
2. **Pre-Publish Audit (`money_stack.audit`)**:
   - Enforces platform character boundaries, zero-hashtag constraints, and anti-AI-slop rules.
   - Enforces 2-step barbell link isolation (root posts stay link-free; final reply carries at most one `https://` link).
   - Verifies shortlink liveness without inflating click counters (`FastUrlVerifier` with SQLite WAL TTL cache).
   - Rewrites tracked shortlinks with bounded canonical SubIDs (`{SHORTCODE}_{FORMAT}_{YYMMDD}`).
3. **Pacing & Firewall (`money_stack.tebar.PacingSubidGuard`)**:
   - Checks `blocked_via_scheduler`, `no_selling`, `blocked_domains`, and `forbidden_keywords`.
   - Fetches recent scheduled/published posts from Tebar to enforce `min_interval_m` and `daily_cap`.
4. **Submission & Ledger (`money_stack.tebar.TebarClient` + `money_stack.storage.fleet_db`)**:
   - Sends idempotent `POST /posts` to `https://api.tebar.app/v1`.
   - Optionally logs `SCHEDULED` intent into `data/fleet_central.db` (WAL mode) with atomic task leases (`active_leases`) to prevent concurrent worker collisions.

## Physical Device Runner (ADB Path)

For workflows that require native on-device composers (e.g., native product tagging):
- `ADBUIDriver` checks `dumpsys window` before every touch event and aborts (`ZERO_MISCLICK_ABORT`) if the device is on any launcher or kids-mode package.
- `DeviceFleetManager` coordinates multi-phone execution via `O_CREAT | O_EXCL` lock files with stale-lock recovery.
- `VisionOCRDriver` (`native/ocr_screen.swift`) extracts text coordinates in ~60–100ms on macOS without relying on Android accessibility dumps.
