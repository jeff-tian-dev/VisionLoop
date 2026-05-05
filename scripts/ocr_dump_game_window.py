#!/usr/bin/env python3
"""
Capture the Clash window and list text using **Tesseract** (:meth:`app.services.vision.VisionService.find_words_ocr`).

Optional **horizontal band scan** (thin full-width strips) so each slice is mostly one text line.

Output:
  - Printed to stdout with flush (unbuffered mode: python -u ...)
  - UTF-8 report (default: repo root ``ocr_dump_latest.txt``)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config
from app.services.vision import VisionService
from app.services.window import WindowService
from app.utils.tesseract_env import configure_tesseract


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _safe_token(s: str) -> str:
    out: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in " .,;:'-+/#$%()*&@!?<>=[]":
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
        else:
            out.append("·")
    return "".join(out).strip()


def _parse_region(s: str) -> Tuple[int, int, int, int]:
    parts = [p.strip() for p in s.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("region must be x,y,w,h")
    return tuple(int(x) for x in parts)  # type: ignore[return-value]


def _resize_max_width(frame: np.ndarray, max_w: int) -> Tuple[np.ndarray, float]:
    if max_w <= 0:
        return frame, 1.0
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame, 1.0
    scale = max_w / w
    new_w = max_w
    new_h = max(1, int(round(h * scale)))
    out = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return out, scale


def _scan_bands(
    frame: np.ndarray,
    *,
    band_height: int,
    band_step: int,
    max_bands: int,
    preprocess: bool,
    white_text: bool,
    verbose: bool,
    min_confidence: int,
    tesseract_config: str,
) -> Tuple[List[str], List[Tuple[int, str]]]:
    fh, fw = frame.shape[:2]
    flat: List[str] = []
    summaries: List[Tuple[int, str]] = []

    y = 0
    n_bands = 0
    while y < fh:
        if max_bands > 0 and n_bands >= max_bands:
            break
        h_eff = min(band_height, fh - y)
        if h_eff < 8:
            break
        region = (0, y, fw, h_eff)
        boxes = VisionService.find_words_ocr(
            frame,
            region=region,
            query=None,
            min_confidence=min_confidence,
            preprocess=preprocess,
            white_text=white_text,
            tesseract_config=tesseract_config,
        )
        ordered = sorted(boxes, key=lambda w: (w.top, w.left))
        for wb in ordered:
            t = _safe_token(wb.text)
            if t:
                flat.append(t)
            if verbose:
                c = wb.confidence
                cs = "nan" if c != c else f"{c:.1f}"
                print(
                    f"    band y={y}..{y + h_eff}  {wb.text!r}  display={t!r}  conf={cs}  "
                    f"box=({wb.left},{wb.top} {wb.width}x{wb.height})",
                    flush=True,
                )
        summary = _safe_token(
            " ".join(wb.text.strip() for wb in sorted(boxes, key=lambda w: w.left))
        )
        if summary:
            summaries.append((y, summary))
        y += band_step
        n_bands += 1

    return flat, summaries


def main() -> int:
    _configure_stdout()
    configure_tesseract()
    parser = argparse.ArgumentParser(
        description="Dump Tesseract OCR text from the current game window (optional band scan)."
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=30,
        help="Tesseract confidence 0–100 (default: 30).",
    )
    parser.add_argument(
        "--preprocess",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply preprocess_bw_ui_text when True (default: true).",
    )
    parser.add_argument(
        "--white-text",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Light UI text on dark (default: true). Use --no-white-text for dark-on-light.",
    )
    parser.add_argument(
        "--tesseract-config",
        type=str,
        default="--psm 7",
        help='Tesseract CLI flags per band/region (default: "--psm 7" one text line per strip).',
    )
    parser.add_argument(
        "--max-frame-width",
        type=int,
        default=960,
        help="Resize capture so width is at most this (default: 960; 0 = full res).",
    )
    parser.add_argument(
        "--max-bands",
        type=int,
        default=24,
        help="Stop after this many horizontal strips (default: 24; 0 = whole frame).",
    )
    parser.add_argument(
        "--band-height",
        type=int,
        default=44,
        help="Height of each horizontal strip (default: 44).",
    )
    parser.add_argument(
        "--band-step",
        type=int,
        default=36,
        help="Vertical step between strips (default: 36).",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Single ROI x,y,w,h in capture pixels (scaled with --max-frame-width).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "ocr_dump_latest.txt",
        help=f"UTF-8 report path (default: {ROOT / 'ocr_dump_latest.txt'}).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Per-word lines for each band (chatty).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the report in the default app when finished (Windows).",
    )
    args = parser.parse_args()

    ws = WindowService()
    if not ws.hwnd:
        msg = (
            "Game window not found. Open Clash of Clans (Google Play Games) and try again.\n"
            "Also written to report file if -o used."
        )
        print(msg, file=sys.stderr, flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(msg + "\n", encoding="utf-8")
        print(f"Wrote: {args.output.resolve()}", flush=True)
        return 1

    frame = ws.screenshot()
    if frame is None or frame.size == 0:
        msg = "Screenshot failed."
        print(msg, file=sys.stderr, flush=True)
        args.output.write_text(msg + "\n", encoding="utf-8")
        print(f"Wrote: {args.output.resolve()}", flush=True)
        return 1

    src_h, src_w = frame.shape[:2]
    frame_work, scale = _resize_max_width(frame, args.max_frame_width)
    cfg = Config()
    cfg.set_target_size_from_frame(frame_work)

    fh, fw = frame_work.shape[:2]
    report: List[str] = []

    def emit(line: str = "") -> None:
        print(line, flush=True)
        report.append(line)

    emit(f"Capture: {src_w}x{src_h} px")
    if scale < 1.0:
        emit(
            f"Working copy: {fw}x{fh} px (uniform scale {scale:.3f}; "
            "use --max-frame-width 0 for full-res)"
        )
    else:
        emit(f"Working copy: {fw}x{fh} px (full width)")
    emit(f"Aspect profile: {cfg.aspect_key}")
    emit(f"OCR: Tesseract  preprocess={args.preprocess}  white_text={args.white_text}")
    emit(f"Tesseract config: {args.tesseract_config!r}")
    emit(f"Report file: {args.output.resolve()}")
    emit()

    all_tokens: List[str] = []
    summaries: List[Tuple[int, str]] = []

    if args.region:
        rx, ry, rw, rh = _parse_region(args.region)
        if scale < 1.0:
            rx = int(round(rx * scale))
            ry = int(round(ry * scale))
            rw = max(1, int(round(rw * scale)))
            rh = max(1, int(round(rh * scale)))
            emit(
                f"Single region (coords scaled with capture to {scale:.3f}x): "
                f"({rx},{ry},{rw}x{rh})"
            )
        else:
            emit(f"Single region: ({rx},{ry},{rw}x{rh})")
        boxes = VisionService.find_words_ocr(
            frame_work,
            region=(rx, ry, rw, rh),
            query=None,
            min_confidence=args.min_confidence,
            preprocess=args.preprocess,
            white_text=args.white_text,
            tesseract_config=args.tesseract_config,
        )
        ordered = sorted(boxes, key=lambda w: (w.top, w.left))
        all_tokens = [_safe_token(wb.text) for wb in ordered]
        all_tokens = [t for t in all_tokens if t]
        line_summary = _safe_token(
            " ".join(wb.text.strip() for wb in sorted(boxes, key=lambda w: w.left))
        )
        if line_summary:
            summaries.append((ry, line_summary))
        if args.verbose:
            for wb in ordered:
                c = wb.confidence
                cs = "nan" if c != c else f"{c:.1f}"
                emit(
                    f"  {wb.text!r}  display={_safe_token(wb.text)!r}  conf={cs}  "
                    f"box=({wb.left},{wb.top} {wb.width}x{wb.height})"
                )
    else:
        emit(
            f"Band scan: height={args.band_height} px, step={args.band_step} px, "
            f"max_bands={args.max_bands or 'all'}"
        )
        emit()
        if args.verbose:
            emit("=== Per-word (all bands) ===")
        all_tokens, summaries = _scan_bands(
            frame_work,
            band_height=args.band_height,
            band_step=args.band_step,
            max_bands=args.max_bands,
            preprocess=args.preprocess,
            white_text=args.white_text,
            verbose=args.verbose,
            min_confidence=args.min_confidence,
            tesseract_config=args.tesseract_config,
        )
        if args.verbose:
            emit()

    emit("=== Words (flattened band order) ===")
    for i, t in enumerate(all_tokens, start=1):
        emit(f"  {i:3}. {t}")
    emit()

    emit("=== Band summaries (y → joined line) ===")
    for y0, s in summaries:
        if s:
            emit(f"  y={y0:4}: {s}")
    emit()

    emit("=== One line (may repeat across bands) ===")
    emit(" ".join(all_tokens))
    emit()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(report) + "\n", encoding="utf-8")
    emit(f"(Also saved {len(report)} lines to disk.)")
    emit()
    emit(f">>> Full report: {args.output.resolve()} <<<")

    if args.open:
        try:
            os.startfile(str(args.output.resolve()))  # type: ignore[attr-defined]
        except AttributeError:
            pass
        except OSError as e:
            print(f"Could not open report file: {e}", file=sys.stderr, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
