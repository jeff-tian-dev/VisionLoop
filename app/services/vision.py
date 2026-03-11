import cv2
import numpy as np
from typing import Optional, Tuple, List
from app.utils.common import get_resource_path
from app.utils.logger import setup_logger

logger = setup_logger("VisionService")

class VisionService:
    """Handles image recognition and processing."""

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
            template_path = str(get_resource_path(f"templates/{template_name}"))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f"Template not found: {template_path}")
                return None, None

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

            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val < threshold:
                return None, None

            t_h, t_w = template.shape[:2]
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
            template_path = str(get_resource_path(f"templates/{template_name}"))
            template = cv2.imread(template_path)
            if template is None:
                logger.error(f"Template not found: {template_path}")
                return None, None, 0.0

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

            result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val < threshold:
                return None, None, float(max_val)

            t_h, t_w = template.shape[:2]
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
            template_path = str(get_resource_path(f"templates/{template_name}"))
            template = cv2.imread(template_path)
            if template is None:
                return []

            if region:
                x, y, w, h = region
                search_img = screen_img[y:y+h, x:x+w]
                offset_x, offset_y = x, y
            else:
                search_img = screen_img
                offset_x, offset_y = 0, 0

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
            
            t_h, t_w = template.shape[:2]
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
