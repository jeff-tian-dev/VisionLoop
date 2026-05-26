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

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

_tess_root = Path(os.environ.get("TESSERACT_ROOT", r"C:\Program Files\Tesseract-OCR"))
_icon = Path("assets/clash_autoloot_logo.ico")

# Only collect the three Qt modules the app actually uses instead of the full PySide6 suite.
# collect_all("PySide6") pulls in Qt3D, QtCharts, QtWebEngine, QtQml, etc. (~250-300 MB wasted).
_pyside6_used_modules = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]
pyside6_datas: list[tuple[str, str]] = []
pyside6_binaries: list[tuple[str, str]] = []
pyside6_hiddenimports: list[str] = []
for _mod in _pyside6_used_modules:
    _d, _b, _h = collect_all(_mod)
    pyside6_datas += _d
    pyside6_binaries += _b
    pyside6_hiddenimports += _h

# Also collect shared PySide6 / shiboken6 runtime data and libs.
pyside6_datas += collect_data_files("PySide6", includes=["*.pyi", "py.typed"])
pyside6_binaries += collect_dynamic_libs("shiboken6")

binaries: list[tuple[str, str]] = list(pyside6_binaries)
datas: list[tuple[str, str]] = [
    ("templates", "templates"),
    ("assets", "assets"),
    *pyside6_datas,
]


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
        "app.ui.qt",
        "app.core",
        "app.services",
        "app.utils",
        "pytesseract",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        *pyside6_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["customtkinter", "tkinter"],
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
    icon=str(_icon) if _icon.is_file() else None,
)
