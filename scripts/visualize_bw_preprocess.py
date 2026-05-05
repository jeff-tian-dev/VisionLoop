#!/usr/bin/env python3
"""
Save one full-frame black/white image using the same ``white_text`` preprocessing
as :meth:`app.services.vision.VisionService.preprocess_bw_ui_text` (brightness floor; no blur),
then optional 8-connected area filtering on ink (`VisionService.filter_binary_ink_by_component_area`).

Writes under ``<repo>/glyph_debug/``:

  - ``full_frame_binary.png`` — single channel 0/255, same pixel size as the working capture
  - ``README.txt`` — dimensions and aspect profile

Default ``--max-frame-width 0`` keeps **native** window resolution.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config
from app.services.vision import VisionService
from app.services.window import WindowService


def _resize_max_width(frame: np.ndarray, max_w: int) -> tuple[np.ndarray, float]:
    if max_w <= 0:
        return frame, 1.0
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame, 1.0
    scale = max_w / w
    new_w = max_w
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA), scale


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export one full-frame binarized screenshot (white-on-dark UI)."
    )
    parser.add_argument(
        "--max-frame-width",
        type=int,
        default=0,
        help="Max capture width (0 = native window).",
    )
    parser.add_argument(
        "--cc-min-area",
        type=int,
        default=None,
        help="Min blob area (default: scaled to frame; 0 = no lower bound).",
    )
    parser.add_argument(
        "--cc-max-area",
        type=int,
        default=None,
        help="Max blob area (default: scaled to frame; 0 = no upper bound).",
    )
    parser.add_argument(
        "--no-cc-area-filter",
        action="store_true",
        help="Skip connected-component area filtering after binarize.",
    )
    parser.add_argument(
        "--brightness-floor",
        type=int,
        default=None,
        help="Grayscale threshold for white_text ink (default: VisionService module constant, usually 220).",
    )
    args = parser.parse_args()

    out_dir = ROOT / "glyph_debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    max_frame_w = max(0, int(args.max_frame_width))

    ws = WindowService()
    if not ws.hwnd:
        (out_dir / "README.txt").write_text(
            "Game window not found. Open Clash and run again.\n", encoding="utf-8"
        )
        print("No window — wrote glyph_debug/README.txt", file=sys.stderr)
        return 1

    frame = ws.screenshot()
    if frame is None or frame.size == 0:
        (out_dir / "README.txt").write_text("Screenshot failed.\n", encoding="utf-8")
        return 1

    src_h, src_w = frame.shape[:2]
    frame_w, scale = _resize_max_width(frame, max_frame_w)
    cfg = Config()
    cfg.set_target_size_from_frame(frame_w)
    fh, fw = frame_w.shape[:2]

    bfloor = args.brightness_floor
    binary = VisionService.preprocess_bw_ui_text(
        frame_w,
        white_text=True,
        brightness_floor=bfloor,
    )
    floor_note = (
        "VisionService default (see _WHITE_TEXT_BRIGHTNESS_FLOOR)"
        if bfloor is None
        else str(int(bfloor))
    )
    cc_note = "disabled (--no-cc-area-filter)"
    if not args.no_cc_area_filter:
        lo, hi = VisionService.scaled_cc_ink_bounds(fw, fh, aspect_key=cfg.aspect_key)
        mn = lo if args.cc_min_area is None else max(0, int(args.cc_min_area))
        mx = hi if args.cc_max_area is None else max(0, int(args.cc_max_area))
        if mn == 0 and mx == 0:
            cc_note = "skipped (cc-min-area and cc-max-area both 0)"
        elif mn == 0:
            binary = VisionService.filter_binary_ink_by_component_area(
                binary, min_area=0, max_area=mx
            )
            cc_note = f"max_area={mx} only"
        elif mx == 0:
            h, w = binary.shape[:2]
            binary = VisionService.filter_binary_ink_by_component_area(
                binary, min_area=mn, max_area=h * w + 1
            )
            cc_note = f"min_area={mn} only"
        else:
            binary = VisionService.filter_binary_ink_by_component_area(
                binary, min_area=mn, max_area=mx
            )
            cc_note = f"min_area={mn}, max_area={mx}"

    out_png = out_dir / "full_frame_binary.png"
    cv2.imwrite(str(out_png), binary)

    readme = f"""Full-frame binary debug
======================

Capture (original): {src_w}x{src_h} px
Working copy: {fw}x{fh} px (max_frame_width={max_frame_w}, scale={scale:.3f})
Aspect profile: {cfg.aspect_key}

File: full_frame_binary.png
  Grayscale 8-bit, values 0 or 255. Black = ink (grayscale >= brightness floor in source). White = background.

White-on-dark brightness floor (gray >= counts as ink): {floor_note}
Preprocess: ``VisionService.preprocess_bw_ui_text(..., white_text=True)``.
CC area filter: {cc_note} (``VisionService.filter_binary_ink_by_component_area``).
"""
    (out_dir / "README.txt").write_text(readme, encoding="utf-8")

    print(f"Wrote {out_png.resolve()}")
    print(f"Wrote {out_dir.resolve() / 'README.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
