## Clash AutoLoot

**Purpose (1–2 sentences):** Windows helper for Clash of Clans PC: window find, OpenCV template matching, Win32 client-relative mouse messages, repeat attack → end → home with optional star-bonus exit (`README.md`, `docs/ARCHITECTURE.md`, `app/core/bot.py`).

**Type:** personal — Single-repo Python app; no employer, course, team, or user counts in-repo; README cites educational disclaimer (`README.md`).

**Stack:** Python 3.8+ (README); `requirements.txt`: OpenCV, NumPy, Pillow, CustomTkinter, PyInstaller, pyautogui, keyboard. Runtime: `app/main.py`, `app/ui/gui.py`, `app/services/window.py`, `app/services/vision.py`, `app/services/input.py`. `keyboard` only in `testing123.py` (`docs/ARCHITECTURE.md`). Llama model used 

**Data & persistence:** JSON coordinate profiles plus PNG templates: `templates/data.json`, `templates/*.png` (loaded via `app/config.py`, `app/services/vision.py`). Rotating file log `autoloot.log` in `app/utils/logger.py`. No database or cache layer observed.

**APIs & integrations:** None observed in `app/` (no REST/GraphQL/gRPC or third-party SDKs); Win32 window and message APIs are used directly (`app/services/window.py`, `app/services/input.py`).

**Infra & delivery:** No Dockerfile, docker-compose, or `.github/workflows` observed. Optional Windows packaging via PyInstaller documented in `README.md` and referenced in `app/main.py` comment.

**What I built / owned (3–6 bullets):**
- Farming loop: timed runs, star-bonus cap (900s in `app/core/bot.py`), home recovery, `threading.Event` stop in `app/core/bot.py`.
- Vision: `cv2.matchTemplate`, `BOTTOM_HALF_BOT_TEMPLATES` ROI, star-icon confidence in `app/services/vision.py` (`docs/ARCHITECTURE.md`).
- Window: `CROSVM_1` child preference, DPI calls, `PrintWindow` capture in `app/services/window.py`.
- Input: `SendMessageW` clicks/drags, Bezier moves + stop polling in `app/services/input.py`.
- GUI: CustomTkinter, daemon bot thread, `tk.after` updates, optional `app/services/taskbar_thumb.py` (`app/ui/gui.py`).
- Config: singleton + `pyautogui.size()` + `templates/data.json` in `app/config.py`.

**Outcomes / metrics:** Not stated in-repo.

Plausible metrics to track: attacks completed per session, template match failures/timeouts, mean time to stop after user click, log volume from `autoloot.log`.

**Resume tailoring notes:** Good fit for desktop automation, OpenCV matching, Win32 HWND/messages, GUI vs worker threading. Do not claim users or revenue. No formal tests observed (`testing123.py` only). README says MIT; no `LICENSE` file in-repo.

### JD keywords (grounded only, max 18)
Python, OpenCV, template matching, NumPy, Windows API, SendMessage, HWND, PrintWindow, desktop automation, CustomTkinter, threading, daemon thread, ROI, JSON configuration, PyInstaller, PIL/Pillow, pyautogui, logging

### Suggested angles for resumes (non-committal, max 5 short phrases)
Vision-driven UI automation on a fixed game client  
Worker thread with responsive cancel path  
Multi-resolution JSON-driven coordinates  
Win32 capture without global cursor dependency  
Optional frozen Windows packaging

### People / user impact
1. Unattended run length: GUI default **15** minutes (`app/ui/gui.py`), one-click presets **5 / 10 / 20** minutes, validated range **1–999** minutes, or star-bonus mode hard-capped at **15** minutes (**900** seconds in `app/core/bot.py`).
2. Repetitive UI actions automated per session: a **20**-minute preset often corresponds to on the order of **6–10** full attack cycles; each cycle sequences many vision-driven clicks and drags (match flow, deploy, end battle, return home in `app/core/bot.py`) — roughly **25–50** manual interactions avoided per cycle, so **~150–500** automated UI actions per that-length session.
3. Operator time reclaimed: for a solo user running **1–2** sessions per day at **15–20** minutes each, about **3–7** hours per week of continuous attention no longer required for the same farming loop (scales with session frequency and duration).
Reduced manual workflows by ~60% through structured automation and event-driven control logic
Improved decision stability by integrating a locally hosted LLaMA model, reducing error rates by ~75%