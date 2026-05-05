"""Print Clash game window outer size, capture size, aspect ratio, and bot profile key."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import resolve_aspect_key
from app.services.window import WindowService


def main() -> None:
    ws = WindowService()
    if not ws.hwnd:
        print(
            "Clash of Clans window not found (Google Play Games: top-level class HwndWrapper*, "
            "title contains 'Clash of Clans', descendant class CROSVM_1)."
        )
        print("Open the game and run this script again.")
        sys.exit(1)

    outer = ws.get_outer_pixel_size()
    if not outer:
        print("Could not read window rectangle.")
        sys.exit(1)

    w, h = outer
    r = w / h
    key = resolve_aspect_key(w, h)
    print(f"Outer window (GetWindowRect): {w} x {h} px")
    print(f"Aspect ratio (w/h): {r:.6f}  (~{w}:{h} = {w / (h or 1):.4f}:1)")

    frame = ws.screenshot()
    if frame is not None:
        fh, fw = frame.shape[:2]
        print(f"Screenshot / vision frame: {fw} x {fh} px")
        if (fw, fh) != (w, h):
            print("  (differs from outer rect — bot uses frame size for scaling)")
    else:
        print("Screenshot: failed")

    if key is None:
        print("Bot aspect profile: NONE (not within 16:9 vs 16:10 tolerance; resize window)")
    else:
        label = "16:9" if key == "16_9" else "16:10"
        print(f"Bot aspect profile: {key} ({label} templates / data.json)")


if __name__ == "__main__":
    main()
