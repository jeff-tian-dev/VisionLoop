# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: one-file GUI build with templates + bundled Tesseract (Windows).
# Before building:  python scripts/prepare_tesseract_bundle.py

from pathlib import Path

project_root = Path(SPEC).resolve().parent

tesseract_root = project_root / "build_assets" / "tesseract"

datas = [("templates", "templates")]
binaries = []

if tesseract_root.is_dir() and (tesseract_root / "tesseract.exe").is_file():
    tessdata = tesseract_root / "tessdata"
    if tessdata.is_dir():
        datas.append((str(tessdata), "tessdata"))
    for f in sorted(tesseract_root.iterdir()):
        if f.is_file() and f.suffix.lower() in (".dll", ".exe"):
            binaries.append((str(f), "."))
else:
    print(
        "WARNING: build_assets/tesseract is missing or incomplete. "
        "OCR will not work in the frozen exe until you run:\n"
        "  python scripts/prepare_tesseract_bundle.py"
    )

block_cipher = None

a = Analysis(
    [str(project_root / "app" / "main.py")],
    pathex=[str(project_root)],
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
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
