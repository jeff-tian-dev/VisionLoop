# Clash AutoLoot

A production Windows desktop application that automates Clash of Clans resource farming using a custom computer vision and Win32 input injection pipeline — deployed with a commercial licensing backend, SaaS billing, and a bundled PyInstaller distribution.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![OpenCV](https://img.shields.io/badge/OpenCV-template%20matching-green.svg)
![FastAPI](https://img.shields.io/badge/backend-FastAPI%20%2B%20Stripe-009688.svg)

---

## What this project is

End-to-end software product:

- **Windows desktop app** — Python / PySide6 (Qt), packaged as a self-contained `.exe` with PyInstaller (Tesseract bundled; no user install required for the shipped build).
- **Computer vision loop** — real-time OpenCV template matching across two aspect-ratio asset packs, plus a Tesseract OCR pipeline for HUD numbers, builder-menu labels, and account name detection.
- **Win32 input injection** — synthetic `SendMessage` mouse events sent directly to the game's child HWND, allowing the bot to run while the user is tabbed out.
- **Commercial licensing backend** — FastAPI service with hardware-bound license key validation, machine fingerprinting via Windows registry + WMI, Stripe webhooks, Postgres, and rate limiting via SlowAPI.

### Desktop features

- **Attack strategies** — Sneaky Goblins, Super Minions, or Valkyries (corner drag deployment, hero activation, earthquake placement).
- **Timed farming or Star Bonus mode** — run for N minutes, or farm until the star bonus is claimed.
- **Ranked attack fill** — optional ranked battle path with a confirmation dialog.
- **Upgrade walls** — when storages are full, OCR the builder menu for **Wall**, then template-match upgrade controls and spend gold/elixir.
- **Multi-run** — switch accounts via OCR on the in-game player list and run a full session per enabled account.
- **Profile settings** — earthquake placement style (Bezier arc vs random fill).
- **License + trial** — hardware-bound keys with background revalidation; time-limited trial with server heartbeat when unlicensed.

---

## Technical highlights

### Window discovery and DPI-aware capture
The game runs inside Google Play Games on PC — a layered Win32 process with an outer `HwndWrapper`-class shell and a nested `CROSVM_1` guest surface. `WindowService` walks the full `EnumChildWindows` tree to resolve the correct child HWND while explicitly skipping Chromium hosts (Discord, Chrome) that share title substrings. DPI awareness is set via `SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)` before any capture, ensuring raw pixel dimensions match template coordinates.

Before farming starts, the GUI validates that the game window is open and its outer size is roughly **16:9** or **16:10** (`Config.check_game_window_aspect_for_start`).

### Aspect-aware coordinate scaling
All authored coordinates and image templates exist at two reference resolutions — **2560×1440** (16:9) and **2560×1600** (16:10). At runtime, `Config` (singleton) detects the capture aspect within a configurable tolerance, loads the matching `data.json`, and proportionally scales every point and scalar to the live screenshot dimensions. Adding a new game UI element means editing the JSON at the reference resolution, not the live size.

### Computer vision pipeline
`VisionService` handles two distinct workloads:

- **Template matching**: OpenCV `matchTemplate` over full or half-frame ROIs (game splits naturally — battle controls on the bottom half, HUD on the top). Thresholds are tuned per-template; common UI elements like the attack button, ranked/farm battle selector, star bonus indicators, wall-upgrade controls, and all hero/troop icons are matched this way.
- **OCR pipeline**: For the resource HUD (gold / elixir / dark elixir), builder **Wall** labels, and player name matching, a preprocessing chain runs before Tesseract: crop ROI → optional linear upscale (3× for HUD digits) → binarization → connected-component filtering → Tesseract `image_to_boxes` / `image_to_data` → word-box grouping → confidence filtering → parsing. The pipeline maps Tesseract pixel boxes back to screen coordinates after upscaling.

### Non-negative loot delta tracking
Raw HUD OCR is noisy frame-to-frame. Rather than trusting absolute reads, `Bot` takes a diff snapshot immediately before each attack (and before wall upgrades when enabled) and accumulates only **non-negative deltas** across (gold, elixir, dark elixir). Negative deltas — which indicate an OCR misread or a wall upgrade spend — are logged with both snapshots but are never added to session totals. A `loot_callback` hook exists for UI integration; the current GUI does not display session totals (progress is written to `autoloot.log`).

### Human-like input injection
All mouse events are posted via `SendMessage(WM_LBUTTONDOWN / WM_LBUTTONUP / WM_MOUSEMOVE)` directly to the game HWND. Drag paths use a randomized Bezier curve with ease-in/ease-out timing and per-call coordinate jitter. Coordinates are clamped to the captured window rect before encoding as `LPARAM`, preventing out-of-bounds messages on resize. This approach requires no cursor hooks and works with the window minimized or behind other windows.

### Multi-account automation via OCR
The multi-run mode switches Clash accounts in sequence. After each account switch, `VisionService` scans the in-game player list using Tesseract and matches the target name with fuzzy / substring logic (tolerates minor OCR artifacts). Session loot resets and the attack loop restarts per account.

### Hardware-bound licensing
`HardwareFingerprint` derives a stable 32-hex machine ID by combining the Windows `MachineGuid` (HKLM registry) with the motherboard serial (WMI). The SHA-256 digest is sent with every validation request, binding the license to the machine on first activation. The client `LicenseManager` runs a background thread that revalidates every 3 hours, with a 30-second retry loop and a 15-minute hard timeout before entering UNREACHABLE state. The bot halts automatically on key revocation.

### FastAPI licensing backend
The `server/` package is a production FastAPI service:

- `/v1/validate` — checks key + fingerprint against Postgres via a stored procedure, handles not-found / revoked / machine-mismatch / expiry responses.
- `/v1/trial/heartbeat` — trial session accounting.
- Stripe webhooks handle subscription lifecycle (new, renewed, canceled, expired).
- SlowAPI rate limiting on public endpoints.
- All database interactions go through async `asyncpg` connection pool.

---

## Architecture

```
app/
├── main.py                  # Entry: Tesseract env → PySide6 GUI
├── config.py                # Aspect detection, data.json loading, coordinate scaling (singleton)
├── core/
│   ├── bot.py               # Attack loop, loot tracking, wall upgrades, multi-run sequencing
│   └── strategies.py        # Troop deployment — Valkyries, Sneaky Goblins, Super Minions;
│                            #   hero activation, earthquake placement (Bezier arc or random fill)
├── services/
│   ├── window.py            # Win32 HWND discovery, DPI-aware BitBlt screenshot
│   ├── input.py             # SendMessage injection, Bezier human_move, scroll
│   ├── vision.py            # OpenCV template matching, Tesseract OCR pipeline, HUD parsing
│   ├── license.py           # HardwareFingerprint, LicenseManager state machine
│   ├── trial.py             # Trial session heartbeat client
│   └── taskbar_thumb.py     # Windows taskbar thumbnail Start/Stop buttons (DWM API)
├── ui/
│   └── qt/                  # PySide6 GUI (sidebar + pages)
│       ├── app.py           # run_gui() entry
│       ├── main_window.py   # MainWindow shell, status bar, navigation
│       ├── bot_controller.py# Bot/license/trial orchestration (Qt signals)
│       ├── theme.py         # Dark theme tokens + QSS
│       ├── widgets.py       # Card, StatusDot, ToggleSwitch, buttons
│       ├── dialogs.py       # Ranked confirm, unpair confirm
│       ├── taskbar_thumb_qt.py
│       └── pages/           # Run, Settings, Players, License, Logs
└── utils/
    ├── common.py            # get_resource_path (dev + frozen), LOCALAPPDATA writable dir
    ├── logger.py            # Rotating file + stderr handler
    ├── player_list_store.py # Multi-run JSON persistence
    ├── profile_settings_store.py
    └── tesseract_env.py     # Tesseract path resolution (bundled vs system vs env var)

scripts/                     # Standalone dev/tuning tools (not imported by the app)
├── extract_top_right_numbers.py
├── ocr_top_center_letters.py
├── preview_earthquake_dots.py
├── record_base_corners.py
└── …

server/                      # FastAPI backend (deployed separately)
├── app.py                   # Routes: /v1/validate, /v1/trial/heartbeat, Stripe webhook
├── db.py                    # asyncpg pool, RPC wrappers
├── stripe_webhook.py        # Subscription lifecycle event handling
├── fingerprint.py           # Server-side fingerprint format validation
├── keys.py                  # Key format regex
└── settings.py              # Pydantic settings (env-based)

templates/
├── 16_9/                    # Asset pack for 16:9 windows (ref 2560×1440)
│   ├── data.json            # Authored UI coordinates + config at reference resolution
│   └── *.png                # Template images (attack, farmbattle, ranked, heroes, troops…)
└── 16_10/                   # Asset pack for 16:10 windows (ref 2560×1600)
```

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.9+ |
| GUI | PySide6 (Qt 6) |
| Computer vision | OpenCV (`matchTemplate`, morphology, thresholding) |
| OCR | Tesseract 5 via pytesseract |
| Win32 | ctypes — `user32`, `gdi32`, `shcore`, `winreg`, DWM |
| Backend | FastAPI + asyncpg + Postgres |
| Billing | Stripe (subscriptions + one-time, webhook lifecycle) |
| Rate limiting | SlowAPI |
| Packaging | PyInstaller (one-file exe, bundled Tesseract) |
| HTTP client | requests (client), httpx (server) |

Client dependencies (`requirements.txt`): OpenCV, NumPy, Pillow, pytesseract, PySide6, PyInstaller, requests.

### Build (PyInstaller)

The local `ClashAutoLoot.spec` is not checked into git. When building the `.exe` after the PySide6 migration:

- Remove any `customtkinter` hidden-import / hook entries from the spec.
- Add PySide6 collection, e.g. `collect_all('PySide6')` or `--collect-submodules PySide6`.
- Ensure the Qt Windows platform plugin (`qwindows.dll`) is bundled (PyInstaller usually picks this up with `collect_all`).

---

## Running locally

```bash
git clone https://github.com/jeff-tian-dev/VisionLoop.git
cd VisionLoop
pip install -r requirements.txt
python -m app.main
```

For OCR in development, install [UB-Mannheim Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (default path `C:\Program Files\Tesseract-OCR\tesseract.exe`) or set `TESSERACT_CMD` to your `tesseract.exe`. The frozen `.exe` bundles Tesseract via `ClashAutoLoot.spec` — see the spec header for `TESSERACT_ROOT` when building.

Build the executable:

```bash
python -m PyInstaller --noconfirm ClashAutoLoot.spec
```

Backend deployment and database setup: [`server/SETUP.md`](server/SETUP.md).

---

*Automating games may violate publisher terms of service. This project is maintained for technical and educational purposes.*
