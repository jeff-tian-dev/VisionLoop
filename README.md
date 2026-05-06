# VisionLoop

A Windows automation bot for Clash of Clans that farms resources using image recognition. The bot automates the attack loop: find a match, deploy troops, return home, and repeat.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## HOW TO USE

### Install

1. Open **[Releases](https://github.com/jeff-tian-dev/VisionLoop/releases)** for this project.
2. Download the latest **`ClashAutoLoot.exe`** (or the main Windows build attached there).
3. Save it somewhere you’re happy to run it from (Desktop or a folder is fine). You can run it as-is; no Python install needed.

### Before you run it

- Use **Windows**.
- Play **Clash of Clans on PC** (for example Google Play Games).
- Run the game in a **normal widescreen window**—either a standard 16:9 shape or a slightly taller 16:10-style layout. Don’t use a random or extreme crop; if the shape isn’t supported, the app may close right after opening with a short message.
- If the game window isn’t open yet, the app can still start—just open Clash before you press **Start** on the bot.

### License key

A valid license key is required to use the bot.

1. After purchasing, you will receive an email with a key in the format `CLASH-XXXX-XXXX-XXXX-XXXX`.
2. Open the bot and paste the key into the **License Key** field at the top.
3. Click **Activate**. The indicator dot turns **green** when the key is valid.
   - **Green** = valid and ready to use.
   - **Yellow** = checking (or temporarily unable to reach the server — retrying).
   - **Red** = key is empty, invalid, revoked, or the server has been unreachable for more than 15 minutes.
4. The key is **bound to this machine** on first activation. To transfer to a new machine, contact support at [clashautoloot@gmail.com](mailto:clashautoloot@gmail.com).

The bot re-validates the key every 3 hours in the background. If your key is revoked while the bot is running, it will stop automatically.

> **Internet connection required.** The bot validates your license on startup and periodically while running. There is no offline mode.

### Using the app

1. Open **Clash of Clans** and leave the window visible.
2. Double-click **`ClashAutoLoot`** to open it.
3. Enter and activate your **license key** (see above).
4. Pick how you want to attack: **Valkyries**, **Sneaky Goblins**, or **Super Minions**.
4. **Multi-run** (optional): turn it on, then **Player list…** to add the account names you see in-game, choose who runs and who is skipped, and put them in the order you want. At least one account must be set to run.
5. **Ranked attack fill** (optional): only turn this on if you **want** to spend ranked attacks; you’ll get a confirmation screen first.
6. Either type **how many minutes** to farm (or use the quick **5m / 10m / 20m** buttons), or turn on **Star Bonus** to farm until your daily star bonus is done (the timer is turned off in that mode).
7. Click **Start** when you’re ready. Use **Stop** anytime—it should stop within a few seconds. You may also see **Start/Stop** on the **taskbar preview** when you hover the app. You may tab out of the game at this point.

### Star Bonus

With **Star Bonus** on, the bot keeps going until it no longer sees the “you still have a bonus to earn” stars on your home screen, then it stops on its own.

### Multi-run

The app saves your player list as **`player_list.json`** in the **same folder** as **`ClashAutoLoot.exe`**. Order matters: that’s the order it visits accounts. **Skip** means it won’t farm that account this round.

### Ranked attack fill

This uses **ranked** battles instead of regular farming. Only enable it if you’re okay using up ranked attacks during your run.

## For developers

**Technical architecture, subsystems, threading, and where to change vision/bot behavior** are documented in **[`DEVELOPER.md`](DEVELOPER.md)**.

Clone the repo, use Python 3.9+, `pip install -r requirements.txt`, and run `python -m app.main`. To build your own `.exe`, see [`build_assets/README.md`](build_assets/README.md) and `ClashAutoLoot.spec` (PyInstaller).

```bash
python scripts/prepare_tesseract_bundle.py   # optional, if you have this helper
python -m PyInstaller --noconfirm ClashAutoLoot.spec
```

Without bundling Tesseract into `build_assets/tesseract`, multi-run OCR in a custom build may need Tesseract installed on the machine or a `TESSERACT_CMD` environment variable.

## Project Structure

```
Clash_Auto_Loot/
├── app/
│   ├── core/
│   │   ├── bot.py           # Main bot logic and attack loop
│   │   └── strategies.py    # Attack strategies (troop deployment)
│   ├── services/
│   │   ├── input.py         # Mouse/keyboard injection (SendMessage, clamped to capture)
│   │   ├── vision.py        # Template matching and OCR helpers
│   │   ├── window.py        # Window detection and screenshots
│   │   └── taskbar_thumb.py # Windows taskbar preview Start/Stop
│   ├── ui/
│   │   └── gui.py           # CustomTkinter interface
│   ├── utils/
│   │   ├── common.py        # Resource paths, per-aspect template paths
│   │   ├── logger.py        # Logging configuration
│   │   ├── player_list_store.py  # Multi-run player list JSON
│   │   └── tesseract_env.py # Tesseract path for dev and frozen builds
│   ├── config.py            # Aspect selection, scaling, data.json loading
│   └── main.py              # Entry point (Tesseract + GUI)
├── templates/
│   ├── 16_9/                # 16:9 pack (ref 2560×1440)
│   └── 16_10/               # 16:10 pack (ref 2560×1600)
├── requirements.txt
└── README.md
```

## How It Works

1. **Window detection** – Finds the Google Play Games window (`HwndWrapper` shell + `CROSVM_1` child, title contains Clash of Clans) via the Windows API.
2. **Aspect and scaling** – Chooses `16_9` vs `16_10` from the outer window size, loads `templates/<aspect>/data.json`, and scales authored coordinates to the current capture size.
3. **Image recognition** – Uses OpenCV template matching to locate UI elements (Attack, Find Match, Okay, ranked vs farm battle, etc.).
4. **OCR** – Tesseract is used to match player names when switching accounts in multi-run.
5. **Input injection** – Sends mouse clicks and movements to the game window via `SendMessage`, with coordinates clamped to the captured window rectangle.
6. **Attack strategies** – Deploys troops along configurable paths (corners) with human-like movement timing.

## Configuration

- **`templates/16_9/data.json`** and **`templates/16_10/data.json`** – Coordinates and settings at the reference resolutions above.
- **`templates/<aspect>/*.png`** – Image templates for that aspect (attack, farmbattle, ranked battle, emptystar, changeuser, etc.).

## Disclaimer

This project is for educational purposes. Use at your own risk. Automating games may violate the terms of service of Clash of Clans. The authors are not responsible for any consequences of using this software.

## License

MIT License
