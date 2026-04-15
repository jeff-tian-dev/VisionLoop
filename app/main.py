import sys
import os
from multiprocessing import freeze_support

# Ensure project root is on sys.path so "app" package is importable from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui.gui import run_gui
from app.utils.logger import setup_logger
from app.utils.tesseract_env import configure_tesseract

logger = setup_logger("Main")

def main():
    try:
        configure_tesseract()
        logger.info("Starting Application...")
        run_gui()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    freeze_support()
    main()

# python -m PyInstaller --noconfirm --onefile --windowed --name "ClashAutoLoot" --add-data "templates;templates" --paths "." --hidden-import "app" --hidden-import "app.ui" --hidden-import "app.core" --hidden-import "app.services" --hidden-import "app.utils" "app/main.py"

