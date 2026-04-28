import difflib
import math
import re
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image
from typing import Optional, Tuple, List

from app.config import Config
from app.utils.common import get_template_path
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

# Battle bar UI (troops, spells, heroes, siege) and end-of-battle controls sit on the lower half of the screen.
BOTTOM_HALF_BOT_TEMPLATES = frozenset(
    {
        "attack.png",
        "farmbattle.png",
        "rankedbattle.png",
        "attack2.png",
        "rankedattackconfirm.png",
        "surrender.png",
        "endbattle.png",
    }
)


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
    def preprocess_bw_ui_text(bgr: np.ndarray) -> np.ndarray:
        """
        Normalize screenshot regions that look like nameplate / settings text: dark glyphs on a light field.
        Produces a single-channel image suitable for Tesseract.
        """
        if bgr is None or bgr.size == 0:
            return bgr
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

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
        tesseract_config: str = "--psm 11",
        match_alnum_only: bool = False,
        fuzzy_min_ratio: Optional[float] = None,
    ) -> List[OcrWordBox]:
        """
        Locate words via OCR. Tuned for high-contrast black (or dark) text on white / light backgrounds,
        similar to a small, high-contrast player-name crop (dark on light).

        Requires the ``tesseract`` binary on PATH (Windows: install from
        https://github.com/UB-Mannheim/tesseract/wiki ) and ``pip install pytesseract``.

        Args:
            screen_img: BGR screenshot (e.g. from ``WindowService.screenshot()``).
            region: Optional ROI ``(x, y, w, h)`` in screen coordinates.
            query: If set, only return words whose text contains this substring (after normalization).
            min_confidence: Tesseract confidence 0–100; words below this are dropped.
            case_sensitive: Match behavior when ``query`` is set.
            preprocess: If True, apply Otsu binarization (good for clean UI text).
            tesseract_config: Extra Tesseract CLI flags (default sparse text for scattered labels).
            match_alnum_only: If True with ``query``, also match after stripping non-alphanumeric characters
                and allow substring match either way on the compact strings.
            fuzzy_min_ratio: If set (e.g. ``0.8``), also accept tokens whose string similarity to the
                query reaches this ratio (SequenceMatcher).

        Returns:
            List of ``OcrWordBox`` in full-screen coordinates (including ROI offset).
        """
        if pytesseract is None:
            logger.error("pytesseract is not installed; pip install pytesseract and install the Tesseract OCR binary")
            return []

        if screen_img is None or screen_img.size == 0:
            return []

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
            mono = VisionService.preprocess_bw_ui_text(work)
        else:
            mono = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

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
            tesseract_config=tesseract_config,
        )
        rx = re.compile(pattern, flags)
        return [w for w in all_words if rx.search(w.text)]
