# Clash AutoLoot

A Windows automation bot for Clash of Clans that farms resources using image recognition. The bot automates the attack loop: find a match, deploy troops, return home, and repeat.

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- **Multiple attack strategies** – Valkyries, Sneaky Goblins, Super Minions
- **Star Bonus mode** – Automatically stops when the daily star bonus is claimed
- **Configurable duration** – Run for a set number of minutes or use quick presets (5m, 10m, 20m)
- **Auto Upgrade Walls** – Optional wall upgrade logic when resources are full
- **Responsive Stop** – Stops within seconds when you click Stop, even during troop deployment
- **Window handle recovery** – Re-finds the game window each session, so you can close and reopen the game without restarting the bot

## Requirements

- **Windows** (uses Windows API for window capture and input)
- **Clash of Clans** running on PC (e.g. Google Play Games, BlueStacks, or similar)
- **Python 3.8+**
- **Supported resolutions** – 1920×1080 or 2560×1600 (default profile)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/jeff-tian-dev/game-automation-framework.git
   cd game-automation-framework
   ```

2. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Ensure the `templates` folder contains all required image templates and `data.json` for your resolution.

## Usage

1. Open Clash of Clans on your PC.
2. Run the application:
   ```bash
   python -m app.main
   ```
3. Select an attack method (Valkyries, Sneaky Goblins, or Super Minions).
4. Choose duration or enable **Star Bonus** to run until the daily star bonus is claimed.
5. Click **Start** to begin farming.

### Star Bonus Mode

When **Star Bonus** is enabled, the bot runs until the empty star icon is no longer visible on the home screen, indicating the star bonus has been claimed. The duration field is disabled in this mode.

### Building an Executable

Tesseract OCR is bundled into the `.exe` when you use the spec file (Windows). First copy your Tesseract install into `build_assets/tesseract` (ignored by git):

```bash
python scripts/prepare_tesseract_bundle.py
python -m PyInstaller --noconfirm ClashAutoLoot.spec
```

The frozen app resolves `tesseract.exe` and `tessdata` from the PyInstaller temp folder automatically (`app.utils.tesseract_env`).

**Without the bundle step**, the spec still builds, but OCR features will only work if Tesseract is installed on the target PC or you set the `TESSERACT_CMD` environment variable.

**One-liner without the spec** (no bundled Tesseract; templates only):

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name "ClashAutoLoot" --add-data "templates;templates" --paths "." --hidden-import "app" --hidden-import "app.ui" --hidden-import "app.core" --hidden-import "app.services" --hidden-import "app.utils" --hidden-import "pytesseract" "app/main.py"
```

## Project Structure

```
Clash_Auto_Loot/
├── app/
│   ├── core/
│   │   ├── bot.py          # Main bot logic and attack loop
│   │   └── strategies.py   # Attack strategies (troop deployment)
│   ├── services/
│   │   ├── input.py        # Mouse/keyboard injection
│   │   ├── vision.py       # Image template matching
│   │   └── window.py       # Window detection and screenshots
│   ├── ui/
│   │   └── gui.py          # CustomTkinter interface
│   ├── utils/
│   │   ├── common.py       # Resource paths
│   │   └── logger.py       # Logging configuration
│   ├── config.py           # Resolution-based config
│   └── main.py             # Entry point
├── templates/               # Image templates and data.json
├── requirements.txt
└── README.md
```

## How It Works

1. **Window detection** – Finds the Clash of Clans window using the Windows API (supports Google Play Games / CROSVM).
2. **Image recognition** – Uses OpenCV template matching to locate UI elements (Attack button, Find Match, Okay, etc.).
3. **Input injection** – Sends mouse clicks and movements directly to the game window via `SendMessage`.
4. **Attack strategies** – Deploys troops along configurable paths (corners) with human-like movement timing.

## Configuration

- **`templates/data.json`** – Contains coordinate points and settings for 1920×1080 and 2560×1600 resolutions.
- **`templates/*.png`** – Image templates used for UI detection (attack.png, findmatch.png, okay.png, etc.).

## Disclaimer

This project is for educational purposes. Use at your own risk. Automating games may violate the terms of service of Clash of Clans. The authors are not responsible for any consequences of using this software.

## License

MIT License
