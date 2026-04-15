# Build assets (not committed)

Run from the repo root:

```powershell
python scripts/prepare_tesseract_bundle.py
```

This fills `build_assets/tesseract/` from your Windows Tesseract install so `ClashAutoLoot.spec` can bundle it into the `.exe`.
