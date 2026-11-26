# money-stack-public

[![Get Free Scheduler API Key](https://img.shields.io/badge/Scheduler-Claim_Free_API_Key_%E2%86%92-111827?style=for-the-badge)](https://tebar.app/?ref=BLASTER)

**Modular Online Income, Creator & Freelance Automation Stack** — combining omnichannel content scheduling, fail-closed pre-publish guardrails, SubID attribution, 5-layer video deduplication, physical Android ADB + Vision OCR automation, and a trend/freelance opportunity radar.

> **Powered by [Tebar.app](https://tebar.app/?ref=BLASTER)**: `money-stack-public` uses **Tebar.app** as its omnichannel post scheduler, media library, and insights backend.
> 👉 **[Grab the Scheduler API Key Used by This Stack →](https://tebar.app/?ref=BLASTER)**

---

## Income & Automation Pillars

### 1. Creator & Affiliate Publishing Autopilot
| Module | Purpose |
| :--- | :--- |
| `money_stack.tebar` | REST client for [Tebar.app](https://tebar.app/?ref=BLASTER) (`TebarClient`) + config-driven pacing, daily caps, cross-niche keyword firewall, persona firewall, and domain guards (`PacingSubidGuard`). |
| `money_stack.audit` | Fail-closed pre-publish linter (`assert_post_safe`), 2-step barbell link isolation, anti-AI-slop rules, canonical SubID injector (`{SHORTCODE}_{FORMAT}_{YYMMDD}`), and SQLite-cached URL health checks (`FastUrlVerifier`). |
| `money_stack.media` | 5-layer duplicate content detector (`video_dedup`): SHA-256, `ffprobe` metadata, 5-keyframe 64-bit dHash, audio RMS signature, and Levenshtein/Jaccard caption similarity. |
| `money_stack.storage` | Thread-safe SQLite WAL publications ledger and atomic task leases (`fleet_db`). |
| `money_stack.adb` | Physical Android ADB runner with Zero-Misclick launcher protection (`ADBUIDriver`), multi-device lock manager (`DeviceFleetManager`), and Apple Silicon Vision OCR helper (`native/ocr_screen.swift`). |

### 2. Freelance, Bounty & Trend Signal Radar
| Module | Purpose |
| :--- | :--- |
| `money_stack.radar` | Scans GitHub Trending, Hugging Face Trending, and configurable RSS/Atom remote job & bounty feeds (`config/opportunities.json`), scoring matches against your skills and exclusion keywords. |
| `money_stack.jobs` | SQLite WAL opportunity pipeline (`NEW` → `QUALIFIED` → `PROPOSAL_DRAFTED` → `APPLIED` → `WON`) + structured anti-slop proposal brief generator bound to your `config/personas.json`. |

---

## Quick Start

### 1. Get Scheduler Access (Free Tier)
👉 **[Unlock 1-Click Multi-Platform Scheduling & Analytics →](https://tebar.app/?ref=BLASTER)**

### 2. Install & Initialize Config
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Creates .env and config/*.json from *.example.json
money-stack setup
```

Put your API key from **[the Tebar.app Scheduler Portal](https://tebar.app/?ref=BLASTER)** into `.env`:
```env
TEBAR_API_KEY=your_tebar_api_key_here
```

> **Bring Your Own Accounts, Personas & Feeds:** This repository ships with **zero pre-filled real accounts or personal personas**. After running `money-stack setup`:
> 1. Add your own Tebar account UUIDs, handles, shortcodes, and pacing limits in `config/accounts.json` (see [config/accounts.example.json](config/accounts.example.json)).
> 2. Define your own creator/freelancer voices, cadence, themes, and forbidden words in `config/personas.json` (see [config/personas.example.json](config/personas.example.json)).
> 3. Configure your target skills and public RSS/Atom job feeds in `config/opportunities.json` (see [config/opportunities.example.json](config/opportunities.example.json)).

---

## CLI Usage

```bash
# Inspect your configured account policies and personas
money-stack accounts
money-stack accounts --live
money-stack personas

# Lint a 2-step barbell thread before publishing
money-stack audit --platform threads \
  --text "Under-desk cable trays clear 90% of visual clutter." \
  --reply "Clamp tray specs here: https://s.shopee.co.id/AbCd1234"

# Validate pacing, inject canonical SubID, and schedule via Tebar.app
money-stack schedule \
  --account-id 00000000-0000-4000-8000-000000000001 \
  --text "Under-desk cable trays clear 90% of visual clutter." \
  --reply "Clamp tray specs here: https://s.shopee.co.id/AbCd1234" \
  --at "2026-11-26T20:30:00+07:00"

# Scan AI trends + remote job feeds, score against your skills, and save to SQLite
money-stack radar --mode all --save
money-stack opportunities list --min-score 40
money-stack opportunities draft --id 1 --persona tech_minimalist

# Check or register video fingerprints (requires ffmpeg/ffprobe + Pillow)
money-stack dedup path/to/video.mp4 --caption "Desk setup clip" --sku SKU-101 --channel reels

# Inspect connected physical Android ADB devices
money-stack fleet-health
```

---

## Ecosystem & Related Open-Source Tools

`money-stack-public` connects naturally with companion open-source tooling across scraping, micro-SaaS utilities, and AI video/motion production:

### Companion Public Tools (`mzulfaas`)
* **[python-scraper-anti-bot-boilerplate](https://github.com/mzulfaas/python-scraper-anti-bot-boilerplate)** — Zero-dependency Python anti-bot request boilerplate (Client Hints & jittered backoff).
* **[production-scraping-hub](https://github.com/mzulfaas/production-scraping-hub)** — Production scraping architecture & patterns.
* **[b2b-directory-extractor](https://github.com/mzulfaas/b2b-directory-extractor)** — Structured B2B directory lead extraction toolkit.
* **[quick-invoice](https://github.com/mzulfaas/quick-invoice)** — 100% private, client-side invoice generator built with Flutter (offline-capable for freelancers).
* **[safe-pdf](https://github.com/mzulfaas/safe-pdf)** — 100% private, client-side PDF compressor built with Vue 3 & TypeScript.

### Upstream Video, Motion & Content Ecosystem
* **[openmontage](https://github.com/calesthio/openmontage)** & **[whiteboard-animator](https://github.com/masihsultani/whiteboard-animator)** — Programmatic video montage and whiteboard explainer generation.
* **[lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar)**, **[herk-edit-kit](https://github.com/nateherkai/herk-edit-kit)** & **[Motion-graphics-skill](https://github.com/mattypark/Motion-graphics-skill)** — Motion graphics templates and automated short-form editing kits.
* **[gflow-cli](https://github.com/ffroliva/gflow-cli)** & **[anti-slop](https://github.com/miqdadbadjuber/anti-slop)** — Automated video generation workflows and anti-AI-slop copy hygiene.

---

## Optional: Compile Native Vision OCR (macOS)

Eliminates `uiautomator dump` idle timeouts on physical Android screenshots using Apple's `Vision` framework:

```bash
mkdir -p bin
swiftc -O native/ocr_screen.swift -o bin/ocr_screen
```

---

## Running Tests

```bash
pytest
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for architecture details and safety invariants.

---

## License

MIT License — see [LICENSE](LICENSE).
