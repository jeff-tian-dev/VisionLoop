#!/usr/bin/env python3
"""
Extract grouped numbers from the **top-right HUD** using one pipeline:

  1. ROI (see :meth:`app.services.vision.VisionService.numbers_hud_roi_top_right`)
  2. Grayscale + :meth:`~app.services.vision.VisionService.preprocess_bw_ui_text` (``white_text=True``) → black ink on white
  3. :meth:`~app.services.vision.VisionService.filter_binary_ink_by_component_area` (defaults from
     :meth:`~app.services.vision.VisionService.scaled_cc_ink_bounds` for your resolution / aspect)
  4. Tesseract → digit tokens → cluster by similar ``y`` → merged :class:`~app.services.vision.GroupedNumber` list

Default: live game window capture.

Use ``--image`` for a saved BGR screenshot. With ``--no-preprocess``, CC filtering is skipped (not meaningful on arbitrary gray input).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config
from app.services.vision import VisionService
from app.services.window import WindowService
from app.utils.tesseract_env import configure_tesseract


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Top-right HUD numbers: preprocess + CC filter + Tesseract (live window or --image)."
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="BGR/grayscale image path instead of live capture.",
    )
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Skip preprocess_bw_ui_text (also disables CC filter; for pre-binarized images).",
    )
    parser.add_argument(
        "--no-cc-filter",
        action="store_true",
        help="Skip connected-component area filter (still binarize if preprocess is on).",
    )
    parser.add_argument(
        "--cc-min-area",
        type=int,
        default=None,
        help="Min ink blob area in px² (default: resolution-scaled from aspect baseline).",
    )
    parser.add_argument(
        "--cc-max-area",
        type=int,
        default=None,
        help="Max ink blob area in px² (default: resolution-scaled from aspect baseline).",
    )
    args = parser.parse_args()

    configure_tesseract()

    if args.image is not None:
        frame = cv2.imread(str(args.image), cv2.IMREAD_UNCHANGED)
        if frame is None or frame.size == 0:
            print(f"Could not read: {args.image}", file=sys.stderr)
            return 1
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    else:
        ws = WindowService()
        if not ws.hwnd:
            print("Game window not found; use --image or open Clash.", file=sys.stderr)
            return 1
        frame = ws.screenshot()
        if frame is None or frame.size == 0:
            print("Screenshot failed.", file=sys.stderr)
            return 1

    h, w = frame.shape[:2]
    cfg = Config()
    cfg.set_target_size_from_frame(frame)
    roi = VisionService.numbers_hud_roi_top_right(w, h)
    preprocess = not args.no_preprocess
    cc_on = preprocess and not args.no_cc_filter

    auto_lo, auto_hi = VisionService.scaled_cc_ink_bounds(w, h, aspect_key=cfg.aspect_key)
    disp_lo = auto_lo if args.cc_min_area is None else args.cc_min_area
    disp_hi = auto_hi if args.cc_max_area is None else args.cc_max_area

    print(f"Frame {w}x{h}, aspect={cfg.aspect_key}, ROI (x,y,w,h)={roi}")
    print(
        f"Pipeline: preprocess={preprocess} white_text=True cc_filter={cc_on} "
        f"cc_area (min,max)=({disp_lo},{disp_hi})"
        + (" [defaults scaled to frame]" if cc_on and args.cc_min_area is None and args.cc_max_area is None else "")
    )

    groups = VisionService.extract_top_right_hud_numbers(
        frame,
        preprocess=preprocess,
        white_text=True,
        cc_filter_blobs=cc_on,
        cc_min_area=args.cc_min_area,
        cc_max_area=args.cc_max_area,
    )
    if not groups:
        print("No grouped numbers found.")
        return 0

    for i, g in enumerate(groups):
        cx, cy = g.center
        print(
            f"[{i}] text={g.text!r} bbox=({g.left},{g.top},{g.width},{g.height}) "
            f"center=({cx},{cy}) conf={g.confidence:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
