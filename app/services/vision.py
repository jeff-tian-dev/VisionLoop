import difflib
import math
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from typing import Any, Dict, Optional, Tuple, List, Sequence

from app.config import ASPECT_BASELINE, ASPECT_16_10, ASPECT_16_9, Config, resolve_aspect_key
from app.utils.common import ensure_dir, get_resource_path, get_template_path
from app.utils.logger import setup_logger

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional until pip install
    pytesseract = None  # type: ignore

logger = setup_logger("VisionService")


@dataclass(frozen=True)
class OcrWordBox:
    """A single word bounding box in **screen** coordinates (matches `screen_img`)."""

    left: int
    top: int
    width: int
    height: int
    text: str
    confidence: float

    @property
    def center(self) -> Tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


# Top-right HUD OCR ROI size **in pixels at** :data:`app.config.ASPECT_BASELINE` for each aspect.
_NUMBERS_HUD_ROI_AT_BASELINE: Dict[str, Tuple[int, int]] = {
    ASPECT_16_10: (600, 400),  # 2560×1600
    ASPECT_16_9: (550, 350),  # 2560×1440
}
# Cost digits sit just left of the upgrade gold/elixir icons (baseline width × height).
_UPGRADE_COST_LEFT_OF_ICON_ROI_AT_BASELINE: Dict[str, Tuple[int, int]] = {
    ASPECT_16_10: (150, 40),  # 2560×1600
    ASPECT_16_9: (150, 40),  # 2560×1440
}
# ~cap height in px at 1600p for default Y-cluster tolerance scaling.
_NUMBERS_REF_LINE_HEIGHT_PX = 30


@dataclass(frozen=True)
class GroupedNumber:
    """Merged numeric string on one text line (see :meth:`VisionService.extract_grouped_numbers_in_region`)."""

    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def center(self) -> Tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


@dataclass(frozen=True)
class UpgradeCostIconRedness:
    """Gold or elixir upgrade icon match + how red the cost digits immediately left appear."""

    template: str
    found: bool
    match_confidence: float
    redness: float
    cost_roi_xywh: Optional[Tuple[int, int, int, int]]


@dataclass(frozen=True)
class UpgradeCostRednessPair:
    """See :meth:`VisionService.upgrade_cost_redness_by_resource_icons`."""

    gold: UpgradeCostIconRedness
    elixir: UpgradeCostIconRedness


# Battle bar UI (troops, spells, heroes, siege), settings, and end-of-battle controls sit on the lower half.
BOTTOM_HALF_BOT_TEMPLATES = frozenset(
    {
        "attack.png",
        "farmbattle.png",
        "rankedbattle.png",
        "attack2.png",
        "rankedattackconfirm.png",
        "surrender.png",
        "endbattle.png",
        "settings.png",
        "addwall.png",
        "removewall.png",
        "upgrademore.png",
    }
)

# Builder portraits (HV vs BB) sit in the upper HUD; keep matching top-only to dodge village floor.
TOP_HALF_BOT_TEMPLATES = frozenset(
    {
        "mbuilder.png",
        "builder.png",
        "gbuilder.png",
    }
)


# Pixels with gray >= this are treated as light-on-dark UI ink when ``white_text=True``.
_WHITE_TEXT_BRIGHTNESS_FLOOR = 220

# Connected-component ink area limits at :data:`app.config.ASPECT_BASELINE` resolution per aspect.
_CC_INK_AREA_AT_BASELINE: Dict[str, Tuple[int, int]] = {
    ASPECT_16_10: (150, 800),  # 2560×1600
    ASPECT_16_9: (130, 750),  # 2560×1440
}

# Top-center builder / wall-menu OCR: square side in px at each aspect baseline (scaled by width).
_TOP_CENTER_MENU_SQUARE_SIDE_AT_BASELINE: Dict[str, int] = {
    ASPECT_16_10: 1000,  # 2560×1600
    ASPECT_16_9: 1000,  # 2560×1440
}

# Keep-range for CC ink in :meth:`ocr_letters_top_center` / wall-label OCR at baseline (not HUD).
_WALL_MENU_LETTER_CC_AT_BASELINE: Dict[str, Tuple[int, int]] = {
    ASPECT_16_10: (40, 400),  # 2560×1600 — drop blobs < 40 or > 400 px²
    ASPECT_16_9: (35, 350),  # 2560×1440
}


class VisionService:
    """Handles image recognition and processing."""

    @staticmethod
    def _template_scale_xy(screen_img: np.ndarray) -> Tuple[float, float]:
        """Scale from authored ref (:attr:`Config.ref_width` / ``ref_height``) to screenshot size."""
        h, w = screen_img.shape[:2]
        cfg = Config()
        return w / cfg.ref_width, h / cfg.ref_height

    @staticmethod
    def _resize_template_for_screen(
        template: np.ndarray, screen_img: np.ndarray
    ) -> np.ndarray:
        """Resize reference PNG templates to match the current capture."""
        sx, sy = VisionService._template_scale_xy(screen_img)
        if abs(sx - 1.0) < 0.001 and abs(sy - 1.0) < 0.001:
            return template

        t_h, t_w = template.shape[:2]
        new_w = max(1, int(round(t_w * sx)))
        new_h = max(1, int(round(t_h * sy)))
        interp = cv2.INTER_AREA if min(sx, sy) < 1.0 else cv2.INTER_CUBIC
        return cv2.resize(template, (new_w, new_h), interpolation=interp)

    @staticmethod
    def bottom_half_region(screen_img: np.ndarray) -> Tuple[int, int, int, int]:
        """ROI (x, y, w, h) covering the bottom half of the screenshot."""
        h, w = screen_img.shape[:2]
        y0 = h // 2
        return (0, y0, w, h - y0)

    @staticmethod
    def top_half_region(screen_img: np.ndarray) -> Tuple[int, int, int, int]:
        """ROI (x, y, w, h) covering the top half of the screenshot."""
        h, w = screen_img.shape[:2]
        y1 = h // 2
        return (0, 0, w, y1)

    @staticmethod
    def right_half_region(screen_img: np.ndarray) -> Tuple[int, int, int, int]:
        """ROI (x, y, w, h) covering the right half of the screenshot."""
        h, w = screen_img.shape[:2]
        x0 = w // 2
        return (x0, 0, w - x0, h)

    @staticmethod
    def find_template(
        screen_img: np.ndarray, 
        template_name: str, 
        threshold: float = 0.8,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Finds a single occurrence of a template in the screen image.
        Returns (center_x, center_y) or (None, None).
        """
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f"Template not found: {template_path}")
                return None, None
            template = VisionService._resize_template_for_screen(template, screen_img)

            if region:
                x, y, w, h = region
                # Ensure region is within bounds
                h_screen, w_screen = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                     logger.warning(f"Region {region} out of bounds for image size {w_screen}x{h_screen}")
                     return None, None
                
                search_img = screen_img[y:y+h, x:x+w]
                offset_x, offset_y = x, y
            else:
                search_img = screen_img
                offset_x, offset_y = 0, 0

            t_h, t_w = template.shape[:2]
            s_h, s_w = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return None, None

            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val < threshold:
                return None, None

            center_x = offset_x + max_loc[0] + t_w // 2
            center_y = offset_y + max_loc[1] + t_h // 2

            return center_x, center_y

        except Exception as e:
            logger.error(f"Error in find_template: {e}")
            return None, None

    @staticmethod
    def find_template_with_confidence(
        screen_img: np.ndarray,
        template_name: str,
        threshold: float = 0.0,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[Optional[int], Optional[int], float]:
        """
        Finds a template and returns (center_x, center_y, confidence).
        Confidence is 0.0-1.0 from cv2.matchTemplate TM_CCOEFF_NORMED.
        Returns (None, None, confidence) if not found above threshold.
        """
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f"Template not found: {template_path}")
                return None, None, 0.0
            template = VisionService._resize_template_for_screen(template, screen_img)

            if region:
                x, y, w, h = region
                h_screen, w_screen = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    return None, None, 0.0
                search_img = screen_img[y:y+h, x:x+w]
                offset_x, offset_y = x, y
            else:
                search_img = screen_img
                offset_x, offset_y = 0, 0

            t_h, t_w = template.shape[:2]
            s_h, s_w = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return None, None, 0.0

            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val < threshold:
                return None, None, float(max_val)

            center_x = offset_x + max_loc[0] + t_w // 2
            center_y = offset_y + max_loc[1] + t_h // 2

            return center_x, center_y, float(max_val)

        except Exception as e:
            logger.error(f"Error in find_template_with_confidence: {e}")
            return None, None, 0.0

    @staticmethod
    def scaled_upgrade_cost_left_roi_size(screen_w: int, screen_h: int) -> Tuple[int, int]:
        """
        Width × height of the cost-digit crop **just left** of the upgrade gold/elixir icons,
        scaled from :data:`_UPGRADE_COST_LEFT_OF_ICON_ROI_AT_BASELINE` (150×40 @ 2560×1600 / 2560×1440).
        """
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        key = resolve_aspect_key(sw, sh)
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        ref_w, ref_h = ASPECT_BASELINE[key]
        base_rw, base_rh = _UPGRADE_COST_LEFT_OF_ICON_ROI_AT_BASELINE.get(
            key, _UPGRADE_COST_LEFT_OF_ICON_ROI_AT_BASELINE[ASPECT_16_10]
        )
        rw = max(1, int(round(base_rw * sw / float(ref_w))))
        rh = max(1, int(round(base_rh * sh / float(ref_h))))
        return (rw, rh)

    @staticmethod
    def red_hue_fraction(bgr: np.ndarray, *, sat_floor: int = 40, val_floor: int = 40) -> float:
        """
        Fraction of pixels whose hue falls in red/orange-red ranges (OpenCV H 0–179),
        with saturation and value at least ``sat_floor`` / ``val_floor``.
        """
        if bgr is None or bgr.size == 0 or bgr.ndim != 3:
            return 0.0
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sf = max(0, min(255, int(sat_floor)))
        vf = max(0, min(255, int(val_floor)))
        m1 = cv2.inRange(hsv, (0, sf, vf), (10, 255, 255))
        m2 = cv2.inRange(hsv, (170, sf, vf), (180, 255, 255))
        mask = cv2.bitwise_or(m1, m2)
        total = int(bgr.shape[0]) * int(bgr.shape[1])
        return float(cv2.countNonZero(mask)) / float(total) if total > 0 else 0.0

    @staticmethod
    def _clip_rect_xywh(
        x: int, y: int, w: int, h: int, frame_w: int, frame_h: int
    ) -> Optional[Tuple[int, int, int, int]]:
        x2, y2 = x + w, y + h
        x0 = max(0, min(int(x), int(frame_w)))
        y0 = max(0, min(int(y), int(frame_h)))
        x1 = max(0, min(int(x2), int(frame_w)))
        y1 = max(0, min(int(y2), int(frame_h)))
        rw, rh = x1 - x0, y1 - y0
        if rw <= 0 or rh <= 0:
            return None
        return (x0, y0, rw, rh)

    @staticmethod
    def _match_template_top_left(
        screen_img: np.ndarray,
        template_name: str,
        threshold: float,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], float]:
        """
        Best ``cv2.matchTemplate`` match: ``(left, top, t_w, t_h, score)``.
        ``left`` … ``t_h`` are ``None`` when below ``threshold`` or on error (``score`` still set when matching ran).
        """
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f"Template not found: {template_path}")
                return None, None, None, None, 0.0
            template = VisionService._resize_template_for_screen(template, screen_img)

            if region:
                x, y, w, h = region
                h_screen, w_screen = screen_img.shape[:2]
                if x + w > w_screen or y + h > h_screen:
                    return None, None, None, None, 0.0
                search_img = screen_img[y : y + h, x : x + w]
                offset_x, offset_y = x, y
            else:
                search_img = screen_img
                offset_x, offset_y = 0, 0

            t_h, t_w = template.shape[:2]
            s_h, s_w = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return None, None, None, None, 0.0

            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            score = float(max_val)
            if score < threshold:
                return None, None, None, None, score

            left = offset_x + max_loc[0]
            top = offset_y + max_loc[1]
            return left, top, t_w, t_h, score
        except Exception as e:
            logger.error(f"Error in _match_template_top_left: {e}")
            return None, None, None, None, 0.0

    @staticmethod
    def upgrade_cost_redness_by_resource_icons(
        screen_img: np.ndarray,
        *,
        match_threshold: float = 0.8,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> UpgradeCostRednessPair:
        """
        Locate ``upgradegold.png`` and ``upgradeelixir.png`` (under the active aspect folder),
        then measure :meth:`red_hue_fraction` in a **150×40-at-baseline** rectangle immediately to the
        left of each icon (vertically centered on the template).

        Updates :class:`~app.config.Config` from ``screen_img`` so template paths match aspect.
        """
        miss_gold = UpgradeCostIconRedness("upgradegold.png", False, 0.0, 0.0, None)
        miss_elixir = UpgradeCostIconRedness("upgradeelixir.png", False, 0.0, 0.0, None)

        if screen_img is None or screen_img.size == 0:
            return UpgradeCostRednessPair(miss_gold, miss_elixir)

        cfg = Config()
        cfg.set_target_size_from_frame(screen_img)
        frame_h, frame_w = screen_img.shape[:2]
        roi_w, roi_h = VisionService.scaled_upgrade_cost_left_roi_size(frame_w, frame_h)

        def one(template: str) -> UpgradeCostIconRedness:
            left, top, tw, th, conf = VisionService._match_template_top_left(
                screen_img, template, match_threshold, region
            )
            if left is None or top is None or tw is None or th is None:
                return UpgradeCostIconRedness(template, False, conf, 0.0, None)
            rx = int(left) - roi_w
            ry = int(top) + (int(th) - roi_h) // 2
            clipped = VisionService._clip_rect_xywh(rx, ry, roi_w, roi_h, frame_w, frame_h)
            if clipped is None:
                return UpgradeCostIconRedness(template, True, conf, 0.0, None)
            x0, y0, cw, ch = clipped
            crop = screen_img[y0 : y0 + ch, x0 : x0 + cw]
            red = VisionService.red_hue_fraction(crop)
            return UpgradeCostIconRedness(template, True, conf, red, clipped)

        return UpgradeCostRednessPair(
            one("upgradegold.png"),
            one("upgradeelixir.png"),
        )

    @staticmethod
    def find_all_templates(
        screen_img: np.ndarray,
        template_name: str,
        threshold: float = 0.85,
        region: Optional[Tuple[int, int, int, int]] = None,
        use_grayscale: bool = False
    ) -> List[Tuple[int, int]]:
        """
        Finds all occurrences of a template.
        Returns a list of (x, y) coordinates.
        """
        try:
            template_path = str(get_template_path(template_name))
            template = cv2.imread(template_path)
            if template is None:
                return []
            template = VisionService._resize_template_for_screen(template, screen_img)

            if region:
                x, y, w, h = region
                search_img = screen_img[y:y+h, x:x+w]
                offset_x, offset_y = x, y
            else:
                search_img = screen_img
                offset_x, offset_y = 0, 0

            t_h, t_w = template.shape[:2]
            s_h, s_w = search_img.shape[:2]
            if t_w > s_w or t_h > s_h:
                return []

            if use_grayscale:
                search_gray = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
                template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                
                # Morphological processing (TopHat) to highlight features
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
                search_processed = cv2.morphologyEx(search_gray, cv2.MORPH_TOPHAT, kernel)
                template_processed = cv2.morphologyEx(template_gray, cv2.MORPH_TOPHAT, kernel)
                
                # Blur
                search_processed = cv2.GaussianBlur(search_processed, (3, 3), 0)
                template_processed = cv2.GaussianBlur(template_processed, (3, 3), 0)
                
                result = cv2.matchTemplate(search_processed, template_processed, cv2.TM_CCOEFF_NORMED)
            else:
                result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)

            yloc, xloc = (result >= threshold).nonzero()
            
            points = []
            
            for (px, py) in zip(xloc, yloc):
                cx = offset_x + px + t_w // 2
                cy = offset_y + py + t_h // 2
                points.append((cx, cy))

            # Filter duplicates (non-maximum suppression-ish)
            filtered = []
            radius = min(t_w, t_h) // 2
            
            for pt in points:
                # Check if point is far enough from existing filtered points
                if all(((pt[0] - f[0])**2 + (pt[1] - f[1])**2)**0.5 > radius for f in filtered):
                    filtered.append(pt)

            return filtered

        except Exception as e:
            logger.error(f"Error in find_all_templates: {e}")
            return []

    @staticmethod
    def get_color_fraction(img: np.ndarray, target_hsv: Tuple[int, int, int], tolerance: int = 5) -> float:
        """
        Calculates the fraction of pixels matching a specific HSV color.
        target_hsv: (H, S, V) where H is 0-179.
        """
        if img is None: return 0.0
        
        hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        target_hue = target_hsv[0]
        
        h_min = max(0, target_hue - tolerance)
        h_max = min(179, target_hue + tolerance)
        
        # Hardcoded S/V ranges from original code (100-255)
        lower = np.array([h_min, 100, 100], dtype=np.uint8)
        upper = np.array([h_max, 255, 255], dtype=np.uint8)
        
        mask = cv2.inRange(hsv_img, lower, upper)
        matched = cv2.countNonZero(mask)
        total = img.shape[0] * img.shape[1]
        
        return matched / total if total > 0 else 0.0

    @staticmethod
    def find_leftmost_pixel(img: np.ndarray, target_hsv: Tuple[int, int, int], tolerance: int = 5) -> Tuple[Optional[int], Optional[int]]:
        """Finds the leftmost pixel matching the target color."""
        if img is None: return None, None
        
        hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        target_hue = target_hsv[0]
        
        h_min = max(0, target_hue - tolerance)
        h_max = min(179, target_hue + tolerance)
        
        lower = np.array([h_min, 100, 100], dtype=np.uint8)
        upper = np.array([h_max, 255, 255], dtype=np.uint8)
        
        mask = cv2.inRange(hsv_img, lower, upper)
        ys, xs = np.nonzero(mask)
        
        if len(xs) == 0:
            return None, None
            
        min_idx = np.argmin(xs)
        return int(xs[min_idx]), int(ys[min_idx])

    @staticmethod
    def preprocess_bw_ui_text(
        bgr: np.ndarray,
        *,
        white_text: bool = False,
        brightness_floor: int | None = None,
    ) -> np.ndarray:
        """
        Normalize high-contrast UI text to **black glyphs on white** (single channel, 0 / 255).

        ``white_text=False`` (default): dark glyphs on a light background (Otsu).
        ``white_text=True``: light glyphs on dark; only pixels with grayscale >=
        ``brightness_floor`` (default :data:`_WHITE_TEXT_BRIGHTNESS_FLOOR`) count as ink
        (strict, no blur), then mapped to black-on-white.
        """
        if bgr is None or bgr.size == 0:
            return bgr
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if white_text:
            floor = (
                _WHITE_TEXT_BRIGHTNESS_FLOOR
                if brightness_floor is None
                else max(0, min(255, int(brightness_floor)))
            )
            bright = np.where(gray >= floor, np.uint8(255), np.uint8(0))
            binary = cv2.bitwise_not(bright)
        else:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    @staticmethod
    def filter_binary_ink_by_component_area(
        binary: np.ndarray,
        *,
        min_area: int = 150,
        max_area: int = 800,
        ink_value: int = 0,
        background_value: int = 255,
    ) -> np.ndarray:
        """
        On a single-channel binary image (e.g. from :meth:`preprocess_bw_ui_text`), treat pixels
        equal to ``ink_value`` as foreground, run 8-connected labeling, and set any component with
        area outside ``[min_area, max_area]`` to ``background_value``.
        """
        if binary is None or binary.size == 0 or binary.ndim != 2:
            return binary
        lo, hi = int(min_area), int(max_area)
        if lo > hi:
            lo, hi = hi, lo
        ink_mask = np.uint8(np.where(binary == ink_value, 255, 0))
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            ink_mask, connectivity=8
        )
        out = np.asarray(binary, dtype=np.uint8, order="C").copy()
        bg = np.uint8(background_value)
        for i in range(1, int(num_labels)):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < lo or area > hi:
                out[labels == i] = bg
        return out

    @staticmethod
    def scaled_cc_ink_bounds(
        screen_w: int,
        screen_h: int,
        *,
        aspect_key: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        ``(min_area, max_area)`` for :meth:`filter_binary_ink_by_component_area`, scaled from the
        aspect baseline: **16:10** → 150 / 800 @ 2560×1600; **16:9** → 130 / 750 @ 2560×1440.

        Scales by ``(screen_w / ref_w) * (screen_h / ref_h)`` (blob pixel area vs capture size).
        """
        key = aspect_key or resolve_aspect_key(int(screen_w), int(screen_h))
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        base_min, base_max = _CC_INK_AREA_AT_BASELINE.get(
            key, _CC_INK_AREA_AT_BASELINE[ASPECT_16_10]
        )
        ref_w, ref_h = ASPECT_BASELINE[key]
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        scale = (sw / float(ref_w)) * (sh / float(ref_h))
        return (
            max(1, int(round(base_min * scale))),
            max(1, int(round(base_max * scale))),
        )

    @staticmethod
    def scaled_top_center_menu_side(
        screen_w: int,
        screen_h: int,
        *,
        aspect_key: Optional[str] = None,
    ) -> int:
        """
        Square side length (px) for :meth:`top_middle_square_roi` / builder-menu OCR, scaled from
        the aspect baseline by **width** (``1000`` @ 2560 for both 16:10 and 16:9).
        """
        key = aspect_key or resolve_aspect_key(int(screen_w), int(screen_h))
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        base_side = int(_TOP_CENTER_MENU_SQUARE_SIDE_AT_BASELINE.get(key, 1000))
        ref_w, _ref_h = ASPECT_BASELINE[key]
        sw = max(1, int(screen_w))
        return max(1, int(round(base_side * sw / float(ref_w))))

    @staticmethod
    def scaled_wall_menu_cc_ink_bounds(
        screen_w: int,
        screen_h: int,
        *,
        aspect_key: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        ``(min_area, max_area)`` for wall / builder-menu letter OCR — **16:10** → 40 / 400 @ 2560×1600;
        **16:9** → 35 / 350 @ 2560×1440. Scales by ``(screen_w / ref_w) * (screen_h / ref_h)``.
        """
        key = aspect_key or resolve_aspect_key(int(screen_w), int(screen_h))
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        base_min, base_max = _WALL_MENU_LETTER_CC_AT_BASELINE.get(
            key, _WALL_MENU_LETTER_CC_AT_BASELINE[ASPECT_16_10]
        )
        ref_w, ref_h = ASPECT_BASELINE[key]
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        scale = (sw / float(ref_w)) * (sh / float(ref_h))
        return (
            max(1, int(round(base_min * scale))),
            max(1, int(round(base_max * scale))),
        )

    @staticmethod
    def _ocr_query_matches(
        raw: str,
        query_norm: str,
        *,
        case_sensitive: bool,
        match_alnum_only: bool,
        fuzzy_min_ratio: Optional[float],
    ) -> bool:
        if not query_norm:
            return False

        def norm_text(s: str) -> str:
            s = s.strip()
            return s if case_sensitive else s.lower()

        r = norm_text(raw)
        if query_norm in r:
            return True

        if match_alnum_only:
            ar = re.sub(r"[^a-z0-9]", "", r.lower())
            aq = re.sub(r"[^a-z0-9]", "", query_norm.lower())
            if aq and aq in ar:
                return True
            # OCR is a fragment of the configured name — require a large enough fragment so
            # two-letter side labels cannot match a long username.
            if (
                aq
                and ar
                and ar in aq
                and len(ar) >= max(4, int(0.55 * len(aq)))
            ):
                return True

        if fuzzy_min_ratio is not None:
            cr = (
                re.sub(r"[^a-z0-9]", "", r.lower())
                if match_alnum_only
                else (r if case_sensitive else r.lower())
            )
            cq = (
                re.sub(r"[^a-z0-9]", "", query_norm.lower())
                if match_alnum_only
                else query_norm
            )
            if len(cq) < 3:
                return False
            lo, hi = sorted((len(cr), len(cq)))
            if hi and lo / hi < 0.5:
                return False
            ratio = difflib.SequenceMatcher(None, cq, cr).ratio()
            if ratio >= fuzzy_min_ratio:
                return True

        return False

    @staticmethod
    def _ocr_username_match_tier(
        raw: str,
        query_norm: str,
        *,
        case_sensitive: bool,
        match_alnum_only: bool,
        fuzzy_min_ratio: Optional[float],
    ) -> int:
        """
        Rank how well ``raw`` matches the username (higher is better).
        Used to pick a click target: prefer full name in OCR, then longest token, then confidence.
        """
        if not query_norm:
            return 0

        def norm_text(s: str) -> str:
            s = s.strip()
            return s if case_sensitive else s.lower()

        r = norm_text(raw)
        ar = re.sub(r"[^a-z0-9]", "", r.lower()) if match_alnum_only else ""
        aq = re.sub(r"[^a-z0-9]", "", query_norm.lower()) if match_alnum_only else ""

        if match_alnum_only and aq and aq in ar:
            return 3
        if query_norm in r:
            return 2
        if (
            match_alnum_only
            and aq
            and ar
            and ar in aq
            and len(ar) >= max(4, int(0.55 * len(aq)))
        ):
            return 1
        # Remaining hits are fuzzy-only (still a valid match from find_words_ocr).
        return 0

    @staticmethod
    def find_words_ocr(
        screen_img: np.ndarray,
        region: Optional[Tuple[int, int, int, int]] = None,
        *,
        query: Optional[str] = None,
        min_confidence: int = 30,
        case_sensitive: bool = False,
        preprocess: bool = True,
        white_text: bool = False,
        tesseract_config: str = "--psm 11",
        match_alnum_only: bool = False,
        fuzzy_min_ratio: Optional[float] = None,
        cc_filter_blobs: bool = False,
        cc_min_area: Optional[int] = None,
        cc_max_area: Optional[int] = None,
        brightness_floor: Optional[int] = None,
        save_preprocess_png: Optional[Path] = None,
    ) -> List[OcrWordBox]:
        """
        Locate words via OCR. With default preprocessing: dark glyphs on a light field.

        Pass ``white_text=True`` for light glyphs on dark (see :meth:`preprocess_bw_ui_text`).
        Optional ``brightness_floor`` overrides the default strict threshold when ``white_text``
        and ``preprocess`` are True.
        If ``cc_filter_blobs`` is True (with ``preprocess``), run
        :meth:`filter_binary_ink_by_component_area` on the binarized ROI before Tesseract.
        When ``cc_min_area`` / ``cc_max_area`` are omitted, they follow :meth:`scaled_cc_ink_bounds`
        for the full-frame size.

        Requires the ``tesseract`` binary on PATH (Windows: install from
        https://github.com/UB-Mannheim/tesseract/wiki ) and ``pip install pytesseract``.

        Args:
            screen_img: BGR screenshot (e.g. from ``WindowService.screenshot()``).
            region: Optional ROI ``(x, y, w, h)`` in screen coordinates.
            query: If set, only return words whose text contains this substring (after normalization).
            min_confidence: Tesseract confidence 0–100; words below this are dropped.
            case_sensitive: Match behavior when ``query`` is set.
            preprocess: If True, apply binarization (Otsu for dark-on-light; strict brightness floor for ``white_text``).
            white_text: If True with ``preprocess``, extract near-white ink (see :data:`_WHITE_TEXT_BRIGHTNESS_FLOOR`) on dark UI.
            tesseract_config: Extra Tesseract CLI flags (default sparse text for scattered labels).
            match_alnum_only: If True with ``query``, also match after stripping non-alphanumeric characters
                and allow substring match either way on the compact strings.
            fuzzy_min_ratio: If set (e.g. ``0.8``), also accept tokens whose string similarity to the
                query reaches this ratio (SequenceMatcher).
            cc_min_area / cc_max_area: Blob size limits; default ``None`` uses :meth:`scaled_cc_ink_bounds`.
            brightness_floor: When set with ``white_text`` and ``preprocess``, passed to
                :meth:`preprocess_bw_ui_text`.

        Returns:
            List of ``OcrWordBox`` in full-screen coordinates (including ROI offset).
        """
        if pytesseract is None:
            logger.error("pytesseract is not installed; pip install pytesseract and install the Tesseract OCR binary")
            return []

        if screen_img is None or screen_img.size == 0:
            return []

        full_h, full_w = screen_img.shape[:2]

        offset_x, offset_y = 0, 0
        work = screen_img
        if region is not None:
            rx, ry, rw, rh = region
            h_s, w_s = screen_img.shape[:2]
            if rx < 0 or ry < 0 or rx + rw > w_s or ry + rh > h_s:
                logger.warning(f"OCR region {region} out of bounds for image {w_s}x{h_s}")
                return []
            work = screen_img[ry : ry + rh, rx : rx + rw]
            offset_x, offset_y = rx, ry

        if preprocess:
            mono = VisionService.preprocess_bw_ui_text(
                work,
                white_text=white_text,
                brightness_floor=brightness_floor,
            )
            if cc_filter_blobs:
                c_lo, c_hi = cc_min_area, cc_max_area
                if c_lo is None or c_hi is None:
                    a_lo, a_hi = VisionService.scaled_cc_ink_bounds(full_w, full_h)
                    if c_lo is None:
                        c_lo = a_lo
                    if c_hi is None:
                        c_hi = a_hi
                mono = VisionService.filter_binary_ink_by_component_area(
                    mono,
                    min_area=int(c_lo),
                    max_area=int(c_hi),
                )
        else:
            mono = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

        if save_preprocess_png is not None:
            try:
                ensure_dir(save_preprocess_png.parent)
                cv2.imwrite(str(save_preprocess_png), mono)
            except Exception as exc:
                logger.warning("Could not save OCR preprocess debug PNG: %s", exc)

        pil = Image.fromarray(mono)
        try:
            data = pytesseract.image_to_data(
                pil, output_type=pytesseract.Output.DICT, config=tesseract_config
            )
        except pytesseract.TesseractNotFoundError:
            logger.error(
                "Tesseract executable not found. Install Tesseract and ensure it is on PATH "
                "(e.g. Windows installer from UB Mannheim)."
            )
            return []

        n = len(data.get("text", []))
        qnorm = None
        if query is not None:
            qnorm = query.strip() if case_sensitive else query.strip().lower()

        words: List[OcrWordBox] = []
        for i in range(n):
            raw = (data["text"][i] or "").strip()
            if not raw:
                continue
            try:
                conf = int(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1
            if conf >= 0 and conf < min_confidence:
                continue
            if qnorm is not None and not VisionService._ocr_query_matches(
                raw,
                qnorm,
                case_sensitive=case_sensitive,
                match_alnum_only=match_alnum_only,
                fuzzy_min_ratio=fuzzy_min_ratio,
            ):
                continue

            left = int(data["left"][i]) + offset_x
            top = int(data["top"][i]) + offset_y
            w = int(data["width"][i])
            h = int(data["height"][i])
            words.append(
                OcrWordBox(
                    left=left,
                    top=top,
                    width=w,
                    height=h,
                    text=raw,
                    confidence=float(conf) if conf >= 0 else math.nan,
                )
            )
        return words

    _TESSERACT_NUMBERS_SPARSE = (
        "--psm 11 -c tessedit_char_whitelist=0123456789+/:MmHh"
    )
    # Same sparse layout as numbers; whitelist restricts to Latin letters only.
    _TESSERACT_LETTERS_SPARSE = (
        "--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    )
    # :meth:`find_wall_labels_top_center_ocr` only; full-alphabet whitelist so W→h confusion is avoided.
    _TESSERACT_WALL_LABEL_SPARSE = "--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

    @staticmethod
    def numbers_hud_roi_top_right(screen_w: int, screen_h: int) -> Tuple[int, int, int, int]:
        """
        Top-right HUD rectangle scaled from the aspect baseline: **600×400** at 16:10 (2560×1600),
        **550×350** at 16:9 (2560×1440).

        Returns ``(x, y, w, h)`` in screen pixels, anchored to the top-right corner.
        """
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        key = resolve_aspect_key(sw, sh)
        if key is None or key not in ASPECT_BASELINE:
            key = ASPECT_16_10
        ref_w, ref_h = ASPECT_BASELINE[key]
        base_rw, base_rh = _NUMBERS_HUD_ROI_AT_BASELINE.get(
            key, _NUMBERS_HUD_ROI_AT_BASELINE[ASPECT_16_10]
        )
        rw = max(1, int(round(base_rw * sw / float(ref_w))))
        rh = max(1, int(round(base_rh * sh / float(ref_h))))
        x = max(0, sw - rw)
        y = 0
        return (x, y, rw, rh)

    @staticmethod
    def top_middle_square_roi(
        screen_w: int,
        screen_h: int,
        side: Optional[int] = None,
        *,
        aspect_key: Optional[str] = None,
    ) -> Tuple[int, int, int, int]:
        """
        A square anchored to the **top center**: ``y = 0``, horizontal centering,
        width/height at most ``side`` (clamped to the frame).

        ``side`` omitted → :meth:`scaled_top_center_menu_side` (~1000 px @ 2560 wide for 16:10 / 16:9).
        """
        sw = max(1, int(screen_w))
        sh = max(1, int(screen_h))
        s = (
            int(side)
            if side is not None
            else VisionService.scaled_top_center_menu_side(sw, sh, aspect_key=aspect_key)
        )
        rw = max(1, min(int(s), sw))
        rh = max(1, min(int(s), sh))
        x = max(0, (sw - rw) // 2)
        y = 0
        return (x, y, rw, rh)

    @staticmethod
    def ocr_letters_top_center(
        screen_img: np.ndarray,
        *,
        side: Optional[int] = None,
        min_confidence: int = 0,
        white_text: bool = True,
        brightness_floor: Optional[int] = None,
        cc_filter_blobs: bool = True,
        cc_min_area: Optional[int] = None,
        cc_max_area: Optional[int] = None,
        tesseract_config: Optional[str] = None,
        save_preprocess_png: Optional[Path] = None,
    ) -> List[OcrWordBox]:
        """
        **Builder-menu style OCR:** crop a :meth:`top_middle_square_roi`, run the same preprocess +
        optional CC path as HUD numbers (CC defaults: :meth:`scaled_wall_menu_cc_ink_bounds`),
        then Tesseract with :data:`_TESSERACT_LETTERS_SPARSE`
        (PSM 11 + A–Z whitelist). Returns letter-only word boxes in **full-frame** coordinates.

        ``side`` omitted → resolution-scaled menu square (~1000 @ 2560).
        """
        if screen_img is None or screen_img.size == 0:
            return []
        h_s, w_s = screen_img.shape[:2]
        aspect_k = resolve_aspect_key(w_s, h_s)
        roi = VisionService.top_middle_square_roi(w_s, h_s, side=side, aspect_key=aspect_k)
        cfg = (
            VisionService._TESSERACT_LETTERS_SPARSE.strip()
            if tesseract_config is None
            else str(tesseract_config).strip()
        )
        c_lo, c_hi = cc_min_area, cc_max_area
        if cc_filter_blobs:
            wm_lo, wm_hi = VisionService.scaled_wall_menu_cc_ink_bounds(
                w_s, h_s, aspect_key=aspect_k
            )
            if c_lo is None:
                c_lo = wm_lo
            if c_hi is None:
                c_hi = wm_hi
        words = VisionService.find_words_ocr(
            screen_img,
            region=roi,
            min_confidence=max(0, int(min_confidence)),
            preprocess=True,
            white_text=white_text,
            brightness_floor=brightness_floor,
            tesseract_config=cfg,
            cc_filter_blobs=cc_filter_blobs,
            cc_min_area=c_lo,
            cc_max_area=c_hi,
            save_preprocess_png=save_preprocess_png,
        )
        letter_only = re.compile(r"^[A-Za-z]+$")
        out: List[OcrWordBox] = []
        for b in words:
            t = b.text.strip()
            if letter_only.fullmatch(t):
                out.append(b)
        return out

    @staticmethod
    def find_wall_labels_top_center_ocr(
        screen_img: np.ndarray,
        *,
        side: Optional[int] = None,
        min_confidence: int = 0,
        white_text: bool = True,
        brightness_floor: Optional[int] = None,
        cc_filter_blobs: bool = True,
        cc_min_area: Optional[int] = None,
        cc_max_area: Optional[int] = None,
        tesseract_config: Optional[str] = None,
    ) -> Optional[Tuple[int, int]]:
        """
        Same pipeline as :meth:`ocr_letters_top_center`, with Tesseract limited to **walWAL** unless
        ``tesseract_config`` overrides. Returns the **center** ``(x, y)`` of the OCR word whose text
        contains **wall** (case-insensitive), **lowest on the screen** (largest ``top + height``).
        ``None`` if no such word. Coordinates are the full word box from Tesseract.

        Writes the binarized ROI (same image passed to Tesseract) to
        ``glyph_debug/wall_find_preprocess.png`` under the app resource root each call.
        """
        cfg = (
            VisionService._TESSERACT_WALL_LABEL_SPARSE.strip()
            if tesseract_config is None
            else str(tesseract_config).strip()
        )
        debug_png = get_resource_path("glyph_debug/wall_find_preprocess.png")
        words = VisionService.ocr_letters_top_center(
            screen_img,
            side=side,
            min_confidence=min_confidence,
            white_text=white_text,
            brightness_floor=brightness_floor,
            cc_filter_blobs=cc_filter_blobs,
            cc_min_area=cc_min_area,
            cc_max_area=cc_max_area,
            tesseract_config=cfg,
            save_preprocess_png=debug_png,
        )
        matches = [b for b in words if "wall" in b.text.lower()]
        if not matches:
            return None
        best = max(matches, key=lambda b: b.top + b.height)
        return best.center

    @staticmethod
    def _ocr_word_y_center(box: OcrWordBox) -> float:
        return box.top + box.height * 0.5

    @staticmethod
    def cluster_ocr_boxes_by_y(
        boxes: List[OcrWordBox], y_tolerance: float
    ) -> List[List[OcrWordBox]]:
        """
        Group OCR boxes that share a text line: union on pairs whose vertical centers
        differ by at most ``y_tolerance`` px.
        """
        if not boxes:
            return []
        n = len(boxes)
        cy = [VisionService._ocr_word_y_center(boxes[i]) for i in range(n)]
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            pi, pj = find(i), find(j)
            if pi != pj:
                parent[pi] = pj

        tol = float(y_tolerance)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(cy[i] - cy[j]) <= tol:
                    union(i, j)

        groups: Dict[int, List[OcrWordBox]] = {}
        for i in range(n):
            r = find(i)
            groups.setdefault(r, []).append(boxes[i])
        out = list(groups.values())
        for cl in out:
            cl.sort(key=lambda b: b.left)
        out.sort(key=lambda cl: VisionService._ocr_word_y_center(cl[0]))
        return out

    @staticmethod
    def merge_numeric_cluster(cluster: Sequence[OcrWordBox]) -> GroupedNumber:
        """Sort left-to-right and union bounding boxes into one :class:`GroupedNumber`."""
        if not cluster:
            return GroupedNumber("", 0, 0, 0, 0, float("nan"))
        parts = sorted(cluster, key=lambda b: b.left)
        text = " ".join(p.text.strip() for p in parts if p.text.strip())
        left = min(p.left for p in parts)
        top = min(p.top for p in parts)
        right = max(p.left + p.width for p in parts)
        bottom = max(p.top + p.height for p in parts)
        confs = [float(p.confidence) for p in parts if not math.isnan(float(p.confidence))]
        conf = float(sum(confs) / len(confs)) if confs else float("nan")
        return GroupedNumber(
            text=text,
            left=left,
            top=top,
            width=max(1, right - left),
            height=max(1, bottom - top),
            confidence=conf,
        )

    @staticmethod
    def extract_grouped_numbers_in_region(
        screen_img: np.ndarray,
        region: Tuple[int, int, int, int],
        *,
        min_confidence: int = 0,
        white_text: bool = True,
        tesseract_config: Optional[str] = None,
        y_tolerance_px: Optional[float] = None,
        cc_filter_blobs: bool = True,
        cc_min_area: Optional[int] = None,
        cc_max_area: Optional[int] = None,
        preprocess: bool = True,
    ) -> List[GroupedNumber]:
        """
        **Pipeline:** ROI crop → grayscale via :meth:`preprocess_bw_ui_text` (``white_text``) →
        black/white mask inverted to ink on white → optional
        :meth:`filter_binary_ink_by_component_area` (defaults from :meth:`scaled_cc_ink_bounds`) →
        Tesseract (digit-friendly config) → digit tokens → cluster by line (similar ``y``) → merge.

        OCR digits-focused tokens in ``region``, keep tokens that contain a digit, cluster by
        similar vertical center (same display line → one number), merge left-to-right.

        ``y_tolerance_px`` defaults to a fraction of ~30 px line height scaled by frame height
        (1600p baseline).
        """
        if screen_img is None or screen_img.size == 0:
            return []

        h_s, w_s = screen_img.shape[:2]
        cfg = f"{VisionService._TESSERACT_NUMBERS_SPARSE}".strip()
        if tesseract_config is not None:
            cfg = tesseract_config

        words = VisionService.find_words_ocr(
            screen_img,
            region=region,
            query=None,
            min_confidence=min_confidence,
            preprocess=preprocess,
            white_text=white_text,
            tesseract_config=cfg,
            cc_filter_blobs=cc_filter_blobs,
            cc_min_area=cc_min_area,
            cc_max_area=cc_max_area,
        )
        digit_words = [w for w in words if re.search(r"\d", w.text)]
        if not digit_words:
            return []

        if y_tolerance_px is None:
            med_h = float(np.median([w.height for w in digit_words]))
            y_tol = max(8.0, med_h * 0.45, float(h_s) * (_NUMBERS_REF_LINE_HEIGHT_PX / 1600.0) * 0.35)
        else:
            y_tol = float(y_tolerance_px)

        clusters = VisionService.cluster_ocr_boxes_by_y(digit_words, y_tol)
        return [VisionService.merge_numeric_cluster(cl) for cl in clusters]

    @staticmethod
    def extract_top_right_hud_numbers(
        screen_img: np.ndarray,
        *,
        min_confidence: int = 0,
        white_text: bool = True,
        tesseract_config: Optional[str] = None,
        y_tolerance_px: Optional[float] = None,
        cc_filter_blobs: bool = True,
        cc_min_area: Optional[int] = None,
        cc_max_area: Optional[int] = None,
        preprocess: bool = True,
    ) -> List[GroupedNumber]:
        """
        Full **top-right HUD** number pipeline on ``screen_img`` (see
        :meth:`extract_grouped_numbers_in_region`). ROI from :meth:`numbers_hud_roi_top_right`.

        Updates :class:`~app.config.Config` capture size / aspect from ``screen_img`` when possible.
        """
        if screen_img is None or screen_img.size == 0:
            return []
        cfg = Config()
        cfg.set_target_size_from_frame(screen_img)
        h_s, w_s = screen_img.shape[:2]
        roi = VisionService.numbers_hud_roi_top_right(w_s, h_s)
        return VisionService.extract_grouped_numbers_in_region(
            screen_img,
            roi,
            min_confidence=min_confidence,
            white_text=white_text,
            tesseract_config=tesseract_config,
            y_tolerance_px=y_tolerance_px,
            cc_filter_blobs=cc_filter_blobs,
            cc_min_area=cc_min_area,
            cc_max_area=cc_max_area,
            preprocess=preprocess,
        )

    @staticmethod
    def extract_top_right_hud_numbers_from_window(
        **kwargs: Any,
    ) -> List[GroupedNumber]:
        """
        Capture the game window and run :meth:`extract_top_right_hud_numbers` (full preprocess +
        CC filter + Tesseract pipeline). Returns an empty list if the window is missing or
        screenshot fails.
        """
        from app.services.window import WindowService

        ws = WindowService()
        if not ws.hwnd:
            return []
        frame = ws.screenshot()
        if frame is None or frame.size == 0:
            return []
        return VisionService.extract_top_right_hud_numbers(frame, **kwargs)

    @staticmethod
    def _ocr_confidence_key(w: OcrWordBox) -> float:
        return -1.0 if math.isnan(w.confidence) else float(w.confidence)

    @staticmethod
    def find_word_on_screen(
        screen_img: np.ndarray,
        word_or_phrase: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        **kwargs,
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Returns the center ``(x, y)`` of the best OCR match for ``word_or_phrase``, or
        ``(None, None)`` if not found.

        Among all tokens that pass filters, picks by: (1) **full alnum name inside OCR token**,
        (2) plain substring, (3) long name fragment, (4) fuzzy; then **longest** OCR token,
        then Tesseract confidence — so a short side label does not beat the full username.
        Extra kwargs are forwarded (e.g. ``min_confidence``, ``preprocess``).
        """
        matches = VisionService.find_words_ocr(
            screen_img, region=region, query=word_or_phrase, **kwargs
        )
        if not matches:
            return None, None
        case_sensitive = bool(kwargs.get("case_sensitive", False))
        match_alnum_only = bool(kwargs.get("match_alnum_only", False))
        fuzzy_min_ratio = kwargs.get("fuzzy_min_ratio")
        qnorm = (
            word_or_phrase.strip()
            if case_sensitive
            else word_or_phrase.strip().lower()
        )

        def pick_key(w: OcrWordBox) -> Tuple[int, int, float]:
            tier = VisionService._ocr_username_match_tier(
                w.text,
                qnorm,
                case_sensitive=case_sensitive,
                match_alnum_only=match_alnum_only,
                fuzzy_min_ratio=fuzzy_min_ratio,
            )
            if match_alnum_only:
                alen = len(re.sub(r"[^a-z0-9]", "", w.text.lower()))
            else:
                alen = len(w.text.strip())
            return (tier, alen, VisionService._ocr_confidence_key(w))

        best = max(matches, key=pick_key)
        return best.center

    @staticmethod
    def find_words_regex(
        screen_img: np.ndarray,
        pattern: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        *,
        min_confidence: int = 30,
        preprocess: bool = True,
        white_text: bool = False,
        tesseract_config: str = "--psm 11",
        flags: int = re.IGNORECASE,
    ) -> List[OcrWordBox]:
        """Like :meth:`find_words_ocr` but filter word text with a regex ``pattern``."""
        all_words = VisionService.find_words_ocr(
            screen_img,
            region=region,
            query=None,
            min_confidence=min_confidence,
            preprocess=preprocess,
            white_text=white_text,
            tesseract_config=tesseract_config,
        )
        rx = re.compile(pattern, flags)
        return [w for w in all_words if rx.search(w.text)]
