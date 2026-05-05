# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: run from repo root: python -m PyInstaller --noconfirm ClashAutoLoot.spec"""

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# PyInstaller 6 Analysis expects hook-style (src_dir_or_file, dest_dir) tuples, not Tree().
datas = [
    ("templates", "templates"),
    ("build_assets/tesseract", "."),
    *collect_data_files("customtkinter"),
]

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=[],
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
