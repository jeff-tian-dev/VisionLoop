"""
Capture the live game window and draw the 11 earthquake click positions the bot would
use: same arc sampling as ``AttackStrategy.deploy_spells``, 50% chance to reverse
order, then independent uniform jitter in [-100, 100] px on x and y per click.

Usage (from repo root, game visible):
    python scripts/preview_earthquake_dots.py
    python scripts/preview_earthquake_dots.py --seed 42
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import Config, resolve_aspect_key
from app.core.strategies import AttackStrategy
from app.services.window import WindowService

JITTER_PX = 100
N_DOTS = 11


def main() -> None:
    ap = argparse.ArgumentParser(description="Overlay jittered earthquake placements on a game screenshot.")
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducible jitter / reverse.",
    )
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    ws = WindowService()
    frame = ws.screenshot()
    if frame is None:
        print("Could not capture the game window. Is Clash of Clans open?", file=sys.stderr)
        sys.exit(1)

    h, w = frame.shape[:2]
    if resolve_aspect_key(w, h) is None:
        print(
            f"Window size ~{w}x{h} is not ~16:9 or ~16:10; resize the game and try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = Config()
    cfg.set_target_size_from_frame(frame)

    corners = {k: cfg.get_point(k) for k in ("left", "top", "right")}
    offset = int(cfg.get_scaled("earthquake", 400))
    ltr = AttackStrategy._earthquake_anchor_triplet(corners, offset)
    points = AttackStrategy._sample_arc_through_three(ltr, N_DOTS)
    reversed_order = random.choice((True, False))
    if reversed_order:
        points.reverse()

    jittered: list[tuple[int, int]] = []
    for cx, cy in points:
        jx = cx + random.randint(-JITTER_PX, JITTER_PX)
        jy = cy + random.randint(-JITTER_PX, JITTER_PX)
        jittered.append((jx, jy))

    vis = frame.copy()
    for i, (jx, jy) in enumerate(jittered, start=1):
        if 0 <= jx < w and 0 <= jy < h:
            cv2.circle(vis, (jx, jy), 12, (0, 0, 220), -1, lineType=cv2.LINE_AA)
            cv2.circle(vis, (jx, jy), 12, (220, 220, 255), 2, lineType=cv2.LINE_AA)
            cv2.putText(
                vis,
                str(i),
                (jx - 7, jy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

    rev = "reversed" if reversed_order else "forward"
    print(f"aspect={cfg.aspect_key}  {w}x{h}  order={rev}  jitter=±{JITTER_PX}px")
    cv2.imshow("Earthquake placements (jittered)", vis)
    print("Press any key in the image window to close.")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
