"""
Copy a Windows Tesseract-OCR install into build_assets/tesseract for PyInstaller.

Run before: python -m PyInstaller ClashAutoLoot.spec

Override source: set TESSERACT_INSTALL to the install folder (contains tesseract.exe).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DEST = PROJECT / "build_assets" / "tesseract"
DEFAULT_SRC = Path(os.environ.get("TESSERACT_INSTALL", r"C:\Program Files\Tesseract-OCR"))

IGNORE = {"unins000.dat", "unins000.exe", "unins000.msg"}


def _ignore(_src, names):
    skip = {n for n in names if n in IGNORE}
    skip.update(n for n in names if str(n).endswith(".chm"))
    return skip


def main() -> int:
    exe = DEFAULT_SRC / "tesseract.exe"
    if not exe.is_file():
        print(
            f"Tesseract not found at {exe}. Install with:\n"
            f"  winget install UB-Mannheim.TesseractOCR",
            file=sys.stderr,
        )
        return 1
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(DEFAULT_SRC, DEST, ignore=_ignore)
    print(f"Copied Tesseract to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
