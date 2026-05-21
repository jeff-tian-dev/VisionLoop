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

# Release build (bundles Tesseract + tessdata from %TESSERACT_ROOT% or
# "C:\Program Files\Tesseract-OCR"; see ClashAutoLoot.spec):
#   python -m PyInstaller --noconfirm ClashAutoLoot.spec