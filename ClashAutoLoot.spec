# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ClashAutoLoot (Windows one-file).

Bundled alongside the app (matches ``app.utils.tesseract_env`` frozen layout):
  * ``tesseract.exe`` and all sibling ``*.dll`` from the Tesseract install dir
  * ``tessdata/`` (e.g. ``eng.traineddata``)

Override install path (optional):

    set TESSERACT_ROOT=C:\\Path\\To\\Tesseract-OCR
    python -m PyInstaller --noconfirm ClashAutoLoot.spec
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_tess_root = Path(os.environ.get("TESSERACT_ROOT", r"C:\Program Files\Tesseract-OCR"))

binaries: list[tuple[str, str]] = []
datas: list[tuple[str, str]] = [("templates", "templates")]


def _tessdata_datas(tessdata_dir: Path) -> list[tuple[str, str]]:
    """``Analysis`` expects (src_file, dest_dir) pairs; mirror ``Tree(..., prefix='tessdata')``."""
    out: list[tuple[str, str]] = []
    for _f in sorted(tessdata_dir.rglob("*")):
        if not _f.is_file():
            continue
        _rel = _f.relative_to(tessdata_dir)
        _dest = (
            "tessdata"
            if _rel.parent == Path(".")
            else str(Path("tessdata") / _rel.parent).replace("\\", "/")
        )
        out.append((str(_f), _dest))
    return out


if sys.platform == "win32":
    _tesseract_exe = _tess_root / "tesseract.exe"
    _tessdata = _tess_root / "tessdata"
    if not _tesseract_exe.is_file():
        raise SystemExit(
            "Cannot bundle Tesseract: missing {!s}\n"
            "Install UB-Mannheim Tesseract OCR or set TESSERACT_ROOT to that folder.".format(
                _tesseract_exe
            )
        )
    if not _tessdata.is_dir():
        raise SystemExit(
            "Cannot bundle tessdata: missing {!s}\n"
            "Install Tesseract language data or set TESSERACT_ROOT.".format(_tessdata)
        )

    binaries.append((str(_tesseract_exe), "."))
    for _dll in sorted(_tess_root.glob("*.dll")):
        binaries.append((str(_dll), "."))

    datas.extend(_tessdata_datas(_tessdata))
else:
    print(
        "WARNING: Building on {!s}; Tesseract bundle skipped (Windows-only).".format(sys.platform),
        file=sys.stderr,
    )

a = Analysis(
    ["app\\main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "app",
        "app.ui",
        "app.core",
        "app.services",
        "app.utils",
        "pytesseract",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ClashAutoLoot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
