# money-stack-public

[![Get Free Scheduler API Key](https://img.shields.io/badge/Scheduler-Claim_Free_API_Key_%E2%86%92-111827?style=for-the-badge)](https://tebar.app/?ref=BLASTER)

**Modular Creator & Affiliate Automation Stack** — built with fail-closed pre-publish guardrails, canonical SubID attribution, 5-layer video deduplication, SQLite WAL state tracking, and physical Android ADB + Vision OCR automation.

> **Powered by [Tebar.app](https://tebar.app/?ref=BLASTER)**: `money-stack-public` uses **Tebar.app** as its omnichannel post scheduler, media library, and insights backend.
> 👉 **[Grab the Scheduler API Key Used by This Stack →](https://tebar.app/?ref=BLASTER)**

---

## Core Modules

| Module | Purpose |
| :--- | :--- |
| `money_stack.tebar` | REST client for [Tebar.app](https://tebar.app/?ref=BLASTER) (`TebarClient`) + config-driven pacing, daily caps, cross-niche keyword firewall, and domain guards (`PacingSubidGuard`). |
| `money_stack.audit` | Fail-closed pre-publish linter (`assert_post_safe`), 2-step barbell link isolation, anti-AI-slop rules, canonical SubID injector (`{SHORTCODE}_{FORMAT}_{YYMMDD}`), and SQLite-cached URL health checks (`FastUrlVerifier`). |
| `money_stack.media` | 5-layer duplicate content detector (`video_dedup`): SHA-256, `ffprobe` metadata, 5-keyframe 64-bit dHash, audio RMS signature, and Levenshtein/Jaccard caption similarity. |
| `money_stack.storage` | Thread-safe SQLite WAL publications ledger and atomic task leases (`fleet_db`). |
| `money_stack.adb` | Physical Android ADB runner with Zero-Misclick launcher protection (`ADBUIDriver`), multi-device lock manager (`DeviceFleetManager`), and Apple Silicon Vision OCR helper (`native/ocr_screen.swift`). |

---

## Quick Start

### 1. Get Scheduler Access (Free Tier)
👉 **[Unlock 1-Click Multi-Platform Scheduling & Analytics →](https://tebar.app/?ref=BLASTER)**

### 2. Install & Initialize Config
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Creates .env, config/accounts.json, config/personas.json, and config/rules.json from *.example.*
money-stack setup
```

Put your API key from **[the Tebar.app Scheduler Portal](https://tebar.app/?ref=BLASTER)** into `.env`:
```env
TEBAR_API_KEY=your_tebar_api_key_here
```

> **Bring Your Own Accounts & Personas:** This repository ships with **zero pre-filled real accounts or personal personas**. After running `money-stack setup`:
> 1. Add your own Tebar account UUIDs, handles, shortcodes, and pacing limits in `config/accounts.json` (see [config/accounts.example.json](config/accounts.example.json)).
> 2. Define your own creator voices, cadence, themes, and forbidden words in `config/personas.json` (see [config/personas.example.json](config/personas.example.json)) and link them via `"persona"` in `config/accounts.json`.

---

## CLI Usage

```bash
# List your configured account policies (or pass --live to query Tebar.app)
money-stack accounts
money-stack accounts --live

# List your user-defined personas
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

# Check or register video fingerprints (requires ffmpeg/ffprobe + Pillow)
money-stack dedup path/to/video.mp4 --caption "Desk setup clip" --sku SKU-101 --channel reels

# Inspect connected physical Android ADB devices
money-stack fleet-health
```

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
