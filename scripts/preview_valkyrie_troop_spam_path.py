"""
Capture the live game window and draw the polyline the bot uses for troop spam
(Valkyries use the same path logic as Sneaky / Super Minion): random start corner
(16:9: left or right only; 16:10: top, right, or left), random CW/CCW, five waypoints
closing the loop, each vertex jittered ±10 px like ``AttackStrategy._expand_loc``.

Usage (from repo root, game visible):
    python scripts/preview_valkyrie_troop_spam_path.py
    python scripts/preview_valkyrie_troop_spam_path.py --seed 42
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

from app.config import ASPECT_16_9, Config, resolve_aspect_key
from app.services.window import WindowService


def expand_loc(x: int, y: int) -> tuple[int, int]:
    return x + random.randint(-10, 10), y + random.randint(-10, 10)


def build_ordered_corners(aspect_key: str) -> tuple[list[str], int, int]:
    """Match ``TroopSpamStrategy.execute`` corner ordering."""
    corners = ["top", "right", "bottom", "left"]
    if aspect_key == ASPECT_16_9:
        start_idx = random.choice([1, 3])
    else:
        start_idx = random.choice([0, 1, 3])
    direction = random.choice([1, -1])
    ordered: list[str] = []
    for i in range(5):
        idx = (start_idx + (i * direction)) % 4
        ordered.append(corners[idx])
    return ordered, start_idx, direction


def waypoint_pixels(cfg: Config, ordered_corners: list[str]) -> list[tuple[int, int]]:
    """Same vertex sampling as the live troop-spam drag (start + four legs)."""
    curr_x, curr_y = expand_loc(*cfg.get_point(ordered_corners[0]))
    out = [(curr_x, curr_y)]
    for i in range(len(ordered_corners) - 1):
        next_c = ordered_corners[i + 1]
        tx, ty = expand_loc(*cfg.get_point(next_c))
        out.append((tx, ty))
        curr_x, curr_y = tx, ty
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Overlay troop-spam path (e.g. Valkyries) on a game screenshot."
    )
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for path/jitter.")
    ap.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "glyph_debug" / "valkyrie_troop_spam_path.png",
        help="Where to write the debug PNG.",
    )
    ap.add_argument(
        "--no-show",
        action="store_true",
        help="Skip cv2.imshow (save PNG only).",
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
    ordered, start_idx, direction = build_ordered_corners(cfg.aspect_key)
    pts = waypoint_pixels(cfg, ordered)

    vis = frame.copy()
    thick = max(2, min(w, h) // 400)
    for i in range(len(pts) - 1):
        cv2.line(vis, pts[i], pts[i + 1], (40, 220, 255), thick, cv2.LINE_AA)
    for i, (px, py) in enumerate(pts):
        if not (0 <= px < w and 0 <= py < h):
            continue
        cv2.circle(vis, (px, py), max(8, thick * 4), (0, 180, 255), -1, cv2.LINE_AA)
        cv2.circle(vis, (px, py), max(8, thick * 4), (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(
            vis,
            str(i + 1),
            (px - 8, py + 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (20, 40, 80),
            2,
            cv2.LINE_AA,
        )

    corner_labels = " -> ".join(ordered)
    dir_label = "CW" if direction == 1 else "CCW"
    msg = (
        f"aspect={cfg.aspect_key}  {w}x{h}  start_idx={start_idx}  {dir_label}  "
        f"corners: {corner_labels}"
    )
    print(msg)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), vis)
    print(f"Wrote {args.output}")

    if not args.no_show:
        cv2.imshow("Valkyrie troop-spam path (debug)", vis)
        print("Press any key in the image window to close.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
