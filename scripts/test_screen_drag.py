"""
Standalone test: one screen drag matching ``Bot._leave_builder_base_with_nboat``
(center → ~500px down-left, same ``InputService`` sequence as production).

Run from repo root (with Clash window open):

    python scripts/test_screen_drag.py
"""
import os
import sys
import random
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.window import WindowService
from app.services.input import InputService


def run_drag(window: WindowService) -> None:
    frame = window.screenshot()
    if frame is None:
        raise RuntimeError("Screenshot failed (is the game window visible?)")

    h, w = frame.shape[:2]
    inp = InputService(window, stop_event=None)

    # --- Copied from Bot._leave_builder_base_with_nboat (drag only) ---
    cx = w // 2 + random.randint(-25, 25)
    cy = h // 2 + random.randint(-25, 25)
    cx = max(8, min(w - 8, cx))
    cy = max(8, min(h - 8, cy))

    inp.move(cx, cy, 0)
    inp.mouse_up(cx, cy)
    time.sleep(0.06)

    step = 500
    x2 = max(8, min(w - 8, cx - step))
    y2 = max(8, min(h - 8, cy + step))

    inp.mouse_down(cx, cy)
    inp.human_move(cx, cy, x2, y2, duration=random.uniform(0.35, 0.55))
    inp.mouse_up(x2, y2)
    # --- end copy ---

    print(f"Drag finished: ({cx},{cy}) -> ({x2},{y2}), frame {w}x{h}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Builder Base style screen drag once.")
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Seconds to wait before sending input (focus game window). Default: 2",
    )
    args = parser.parse_args()

    window = WindowService()
    if not window.hwnd:
        print("Clash of Clans window not found. Open the game and retry.", file=sys.stderr)
        sys.exit(1)

    if args.delay > 0:
        print(f"Focus the game window — drag starts in {args.delay:.1f}s...")
        time.sleep(args.delay)

    run_drag(window)


if __name__ == "__main__":
    main()
