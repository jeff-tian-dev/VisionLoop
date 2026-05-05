#!/usr/bin/env python3
"""
Letter OCR on a **top-center square** ROI. Default size and CC ink bounds are **resolution-scaled**
from :data:`app.config.ASPECT_BASELINE` (~**1000** px side @ 2560; **16:10** ink 40–400 px²,
**16:9** 35–350 px² at baseline).

Uses :meth:`app.services.vision.VisionService.ocr_letters_top_center` or, with ``--walls``,
:meth:`~app.services.vision.VisionService.find_wall_labels_top_center_ocr` (returns ``(x,y)`` center).

Default: live game window. Use ``--image`` for a saved screenshot.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.vision import VisionService
from app.services.window import WindowService
from app.utils.tesseract_env import configure_tesseract


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Top-center square: preprocess + Tesseract letters (or wall labels with --walls)."
    )
    parser.add_argument(
        "--walls",
        action="store_true",
        help="Print center (x,y) of the bottom-most OCR word containing 'wall' (find_wall_labels_top_center_ocr).",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="BGR/grayscale image path instead of live capture.",
    )
    parser.add_argument(
        "--side",
        type=int,
        default=0,
        help="Square width/height in px (0 = scale from baseline, ~1000 @ 2560 wide).",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=0,
        help="Min Tesseract confidence 0–100 (default 0, like HUD number script).",
    )
    parser.add_argument(
        "--brightness-floor",
        type=int,
        default=None,
        help="Optional grayscale threshold for white_text (see preprocess_bw_ui_text).",
    )
    parser.add_argument(
        "--no-cc-filter",
        action="store_true",
        help="Skip connected-component ink area filter after binarize.",
    )
    parser.add_argument(
        "--cc-min-area",
        type=int,
        default=None,
        help="Min ink blob px² (default: scaled to frame when CC is on).",
    )
    parser.add_argument(
        "--cc-max-area",
        type=int,
        default=None,
        help="Max ink blob px² (default: scaled to frame when CC is on).",
    )
    parser.add_argument(
        "--dump-roi",
        type=Path,
        default=None,
        help="If set, write the preprocessed (1-channel) ROI PNG Tesseract sees.",
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
    side_arg = None if int(args.side) <= 0 else max(1, int(args.side))
    roi = VisionService.top_middle_square_roi(w, h, side=side_arg)

    ocr_kw = dict(
        side=side_arg,
        min_confidence=max(0, int(args.min_confidence)),
        white_text=True,
        brightness_floor=args.brightness_floor,
        cc_filter_blobs=not args.no_cc_filter,
        cc_min_area=args.cc_min_area,
        cc_max_area=args.cc_max_area,
    )

    if args.walls:
        wall_center = VisionService.find_wall_labels_top_center_ocr(frame, **ocr_kw)
        mode = "wall_center"
    else:
        wall_center = None
        kept = VisionService.ocr_letters_top_center(frame, **ocr_kw)
        mode = "letters_only"

    print(f"Frame {w}x{h}, ROI (x,y,w,h)={roi}")
    if args.walls:
        print(
            f"mode={mode} found={wall_center is not None} "
            f"cc_filter={not args.no_cc_filter} brightness_floor={args.brightness_floor!r}"
        )
    else:
        print(
            f"mode={mode} count={len(kept)} "
            f"cc_filter={not args.no_cc_filter} brightness_floor={args.brightness_floor!r}"
        )

    if args.dump_roi is not None:
        rx, ry, rw, rh = roi
        crop = frame[ry : ry + rh, rx : rx + rw]
        mono = VisionService.preprocess_bw_ui_text(
            crop,
            white_text=True,
            brightness_floor=args.brightness_floor,
        )
        if not args.no_cc_filter:
            c_lo, c_hi = args.cc_min_area, args.cc_max_area
            if c_lo is None or c_hi is None:
                wm_lo, wm_hi = VisionService.scaled_wall_menu_cc_ink_bounds(w, h)
                if c_lo is None:
                    c_lo = wm_lo
                if c_hi is None:
                    c_hi = wm_hi
            mono = VisionService.filter_binary_ink_by_component_area(
                mono, min_area=int(c_lo), max_area=int(c_hi)
            )
        args.dump_roi.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.dump_roi), mono)
        print(f"Wrote preprocess ROI: {args.dump_roi.resolve()}")

    if args.walls:
        if wall_center is None:
            print(f"No word containing 'wall' in ROI.")
            return 0
        print(f"wall word center (full box): x={wall_center[0]} y={wall_center[1]}")
        return 0

    if not kept:
        print(f"No {mode} hits in ROI.")
        return 0

    for i, b in enumerate(kept):
        print(
            f"[{i}] text={b.text!r} bbox=({b.left},{b.top},{b.width},{b.height}) "
            f"conf={b.confidence:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
