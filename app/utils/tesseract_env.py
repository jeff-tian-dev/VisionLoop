"""Resolve Tesseract OCR for development and for PyInstaller one-file builds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger("TesseractEnv")


def _patch_pytesseract_hidden_console() -> None:
    """Hide the console window when ``tesseract.exe`` is spawned from a GUI / windowed process."""
    if sys.platform != "win32":
        return
    flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if flag is None:
        return
    try:
        import pytesseract.pytesseract as pt
    except ImportError:
        return

    _orig = pt.subprocess_args

    def subprocess_args(include_stdout=True):
        kwargs = _orig(include_stdout)
        prev = int(kwargs.get("creationflags", 0))
        kwargs["creationflags"] = prev | flag
        return kwargs

    pt.subprocess_args = subprocess_args  # type: ignore[method-assign]


def _tessdata_dir(install_root: Path) -> Path:
    """Directory that contains ``*.traineddata`` (Tesseract expects TESSDATA_PREFIX to point here on Windows)."""
    return install_root / "tessdata"


def configure_tesseract() -> None:
    """
    Point pytesseract at tesseract.exe and set TESSDATA_PREFIX to the ``tessdata`` folder
    (where ``eng.traineddata`` lives), not the install root.

    Resolution order:
    1. ``TESSERACT_CMD`` env var (full path to tesseract.exe)
    2. Frozen app: ``sys._MEIPASS/tesseract.exe`` and ``sys._MEIPASS/tessdata/``
    3. Dev default: ``C:\\Program Files\\Tesseract-OCR\\tesseract.exe``
    """
    try:
        import pytesseract
    except ImportError:
        return

    _patch_pytesseract_hidden_console()

    if os.environ.get("TESSERACT_CMD"):
        cmd = Path(os.environ["TESSERACT_CMD"])
        pytesseract.pytesseract.tesseract_cmd = str(cmd)
        td = _tessdata_dir(cmd.parent)
        os.environ["TESSDATA_PREFIX"] = str(td.resolve()) + os.sep
        logger.debug("Tesseract from TESSERACT_CMD: %s, tessdata=%s", cmd, td)
        return

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        bundled = base / "tesseract.exe"
        if bundled.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(bundled)
            td = _tessdata_dir(base)
            os.environ["TESSDATA_PREFIX"] = str(td.resolve()) + os.sep
            logger.debug("Tesseract bundled at %s, tessdata=%s", bundled, td)
        else:
            logger.warning("Frozen build: tesseract.exe not found under %s", base)
        return

    win = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if win.is_file():
        pytesseract.pytesseract.tesseract_cmd = str(win)
        td = _tessdata_dir(win.parent)
        os.environ["TESSDATA_PREFIX"] = str(td.resolve()) + os.sep
        logger.debug("Tesseract dev install: %s, tessdata=%s", win, td)
        return

    logger.warning(
        "Tesseract not configured (install with winget install UB-Mannheim.TesseractOCR "
        "or set TESSERACT_CMD)."
    )
