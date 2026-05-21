import math
import time
import random
from typing import Any, List, Optional, Tuple

from app.services.input import InputService
from app.services.vision import VisionService
from app.config import ASPECT_16_9, Config
from app.utils.logger import setup_logger
from app.utils.profile_settings_store import EARTHQUAKE_METHOD_CURVE, EARTHQUAKE_METHOD_RANDOM

logger = setup_logger("Strategies")

# Earthquake arc discretization for fill polygon (same geometry as curve placement, finer steps).
_EARTHQUAKE_REGION_ARC_SAMPLES = 49
# Horizontal line for random-fill region: ``numerator/denominator`` of the way from screen bottom to top
# (0 = bottom edge, denominator = top edge). Image y increases downward.
_EARTHQUAKE_RANDOM_LINE_FROM_BOTTOM = (4, 10)


class AttackStrategy:
    """Base class for attack strategies."""

    def __init__(
        self,
        input_service: InputService,
        vision_service: VisionService,
        config: Config,
        stop_event=None,
        earthquake_method: str = EARTHQUAKE_METHOD_CURVE,
    ):
        self.input = input_service
        self.vision = vision_service
        self.config = config
        self.stop_event = stop_event
        self.earthquake_method = earthquake_method
        self.CORNER_ORDER = ["left", "top", "right", "bottom"]

    def execute(self, frame, stop_event=None):
        raise NotImplementedError

    def _expand_loc(self, x: int, y: int) -> Tuple[int, int]:
        return x + random.randint(-10, 10), y + random.randint(-10, 10)

    def _sync_frame_size(self, frame) -> None:
        self.config.set_target_size_from_frame(frame)

    def _point(self, key: str) -> List[int]:
        return self.config.get_point(key)

    def _scaled_deployment_data(self) -> dict:
        return {key: self._point(key) for key in self.CORNER_ORDER}

    def deploy_heroes(self, frame):
        self._sync_frame_size(frame)
        heroes = ["queen", "warden", "RC", "king", "prince", "dragonduke"]
        random.shuffle(heroes)
        
        deployed_heroes = []

        # Deploy siege machine: Log Launcher or Siege Barracks (only one in the Army)
        roi = self.vision.bottom_half_region(frame)
        ix, iy = self.vision.find_template(
            frame, "loglauncher.png", threshold=0.7, region=roi
        )
        if not ix:
            ix, iy = self.vision.find_template(
                frame, "siegebarracks.png", threshold=0.7, region=roi
            )
        if ix:
            deploy_point = self._get_hero_deploy_point(frame)
            self.input.click(ix, iy, pause=0.2, rand=False)
            self.input.click(*deploy_point, pause=0.2)

        # Loop 1: Deploy Heroes
        for hero in heroes:
            bx, by = self.vision.find_template(
                frame, f"{hero}.png", threshold=0.7, region=roi
            )
            if not bx:
                continue
                
            # Find a deployment point
            deploy_point = self._get_hero_deploy_point(frame)
            
            # Select hero
            self.input.click(bx, by, pause=0.2, rand=False)
            # Deploy
            self.input.click(*deploy_point, pause=0.2)
            
            deployed_heroes.append((bx, by))

        # Loop 2: Activate Abilities
        for (hx, hy) in deployed_heroes:
            self.input.click(hx, hy, pause=0.2)
            if self.stop_event:
                self.stop_event.wait(random.uniform(0.1, 0.2))
            else:
                time.sleep(random.uniform(0.1, 0.2))

    def _hero_corner_xy(self, corner: str) -> Tuple[int, int]:
        """Corner used when building hero deploy lines; on ``16_9``, ``top`` is nudge-scaled."""
        px, py = self.config.get_point(corner)
        if self.config.aspect_key == ASPECT_16_9 and corner == "top":
            py -= self.config.scale_scalar(70)
        return int(px), int(py)

    @staticmethod
    def _quantize_deploy_to_frame(px: float, py: float, fw: int, fh: int) -> Tuple[int, int]:
        """Clamp to ``[0, fw-1]`` x ``[0, fh-1]``, round to nearest pixels."""
        if fw <= 0 or fh <= 0:
            return int(round(px)), int(round(py))
        cx = max(0.0, min(float(fw - 1), float(px)))
        cy = max(0.0, min(float(fh - 1), float(py)))
        return int(round(cx)), int(round(cy))

    def _get_hero_deploy_point(self, frame: Optional[Any] = None) -> Tuple[int, int]:
        c_name = random.choice(["top", "right", "left"])
        c1x, c1y = self._hero_corner_xy(c_name)

        if c_name in ("left", "right"):
            c2x, c2y = self._hero_corner_xy("top")
        else:
            corner = random.choice(["left", "right"])
            c2x, c2y = self._hero_corner_xy(corner)

        t = random.uniform(0, 1)
        xf = c1x + (c2x - c1x) * t
        yf = c1y + (c2y - c1y) * t

        if frame is not None and getattr(frame, "size", 0):
            fh, fw = frame.shape[:2]
            return self._quantize_deploy_to_frame(xf, yf, fw, fh)

        return int(round(xf)), int(round(yf))

    @staticmethod
    def _earthquake_anchor_triplet(data: dict, offset: int) -> Tuple[Tuple[float, float], ...]:
        """Left / top / right drop anchors (same nudge as legacy earthquake logic)."""
        lx, ly = data["left"]
        lx += int(offset * 1.3)
        tx, ty = data["top"]
        ty += int(offset)
        rx, ry = data["right"]
        rx -= int(offset * 1.3)
        return (float(lx), float(ly)), (float(tx), float(ty)), (float(rx), float(ry))

    @staticmethod
    def _sample_arc_through_three(
        ltr: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]],
        n: int,
    ) -> List[Tuple[int, int]]:
        """
        ``n`` points along a circular arc from L to R that passes through T.
        If L,T,R are collinear, uses a quadratic Bezier with control point chosen so t=0.5 hits T.
        """
        L, T, R = ltr
        ax, ay = L
        bx, by = T
        cx, cy = R
        d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))

        if n < 2:
            return [(int(round(L[0])), int(round(L[1])))]

        if abs(d) < 1e-6:
            # Collinear: Bezier B(t) with B(0)=L, B(1)=R, B(0.5)=T  =>  P1 = 2T - L/2 - R/2
            p1x = 2 * bx - 0.5 * ax - 0.5 * cx
            p1y = 2 * by - 0.5 * ay - 0.5 * cy
            out: List[Tuple[int, int]] = []
            for i in range(n):
                t = i / (n - 1)
                u = 1.0 - t
                x = u * u * ax + 2 * u * t * p1x + t * t * cx
                y = u * u * ay + 2 * u * t * p1y + t * t * cy
                out.append((int(round(x)), int(round(y))))
            return out

        a2 = ax * ax + ay * ay
        b2 = bx * bx + by * by
        c2 = cx * cx + cy * cy
        ox = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
        oy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
        r = math.hypot(ax - ox, ay - oy)

        def ang(p: Tuple[float, float]) -> float:
            return math.atan2(p[1] - oy, p[0] - ox)

        phi_l, phi_t, phi_r = ang(L), ang(T), ang(R)
        two_pi = 2.0 * math.pi
        ccw_span = (phi_r - phi_l) % two_pi
        t_ccw = (phi_t - phi_l) % two_pi
        if t_ccw <= ccw_span:
            sweep = ccw_span
        else:
            sweep = ccw_span - two_pi

        out = []
        for i in range(n):
            t = i / (n - 1)
            phi = phi_l + t * sweep
            x = ox + r * math.cos(phi)
            y = oy + r * math.sin(phi)
            out.append((int(round(x)), int(round(y))))
        return out

    @staticmethod
    def _earthquake_horizontal_y(
        frame_h: int, from_bottom_num: int, from_bottom_den: int
    ) -> int:
        """Row ``y`` for a line ``from_bottom_num/from_bottom_den`` of the way from bottom to top."""
        if frame_h <= 0:
            return 0
        h = frame_h
        f = from_bottom_num / float(from_bottom_den)
        return int(round((h - 1) * (1.0 - f)))

    @staticmethod
    def _earthquake_fill_polygon(
        arc_pts: List[Tuple[int, int]], y_line: int
    ) -> List[Tuple[int, int]]:
        """Closed polygon: arc polyline (left→right) then segment along ``y=y_line`` back to start."""
        if len(arc_pts) < 2:
            return list(arc_pts)
        x0, y0 = arc_pts[0]
        x1, y1 = arc_pts[-1]
        return list(arc_pts) + [(x1, y_line), (x0, y_line)]

    @staticmethod
    def _polygon_double_area(poly: List[Tuple[int, int]]) -> float:
        if len(poly) < 3:
            return 0.0
        a = 0.0
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        return a

    @staticmethod
    def _point_in_polygon(px: int, py: int, poly: List[Tuple[int, int]]) -> bool:
        """Even-odd ray test; ``poly`` closed implicitly (last vertex → first not repeated)."""
        n = len(poly)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            ix, iy = poly[i]
            jx, jy = poly[j]
            if (iy > py) != (jy > py):
                x_at = (jx - ix) * (py - iy) / (jy - iy) + ix
                if px < x_at:
                    inside = not inside
            j = i
        return inside

    @staticmethod
    def _random_points_in_polygon(
        poly: List[Tuple[int, int]], frame_w: int, frame_h: int, n_points: int
    ) -> List[Tuple[int, int]]:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x = max(0, min(xs))
        max_x = min(frame_w - 1, max(xs))
        min_y = max(0, min(ys))
        max_y = min(frame_h - 1, max(ys))
        out: List[Tuple[int, int]] = []
        if max_x < min_x or max_y < min_y:
            return out
        for _ in range(n_points):
            for _try in range(1000):
                rx = random.randint(min_x, max_x)
                ry = random.randint(min_y, max_y)
                if AttackStrategy._point_in_polygon(rx, ry, poly):
                    out.append((rx, ry))
                    break
            else:
                ax, ay = poly[max(1, len(poly) // 4)]
                out.append((max(0, min(frame_w - 1, ax)), max(0, min(frame_h - 1, ay))))
        return out

    def _earthquake_curve_points_with_jitter(
        self, ltr: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]
    ) -> List[Tuple[int, int]]:
        points = self._sample_arc_through_three(ltr, 11)
        if random.choice((True, False)):
            points.reverse()
        jitter_px = 100
        return [
            (
                cx + random.randint(-jitter_px, jitter_px),
                cy + random.randint(-jitter_px, jitter_px),
            )
            for cx, cy in points
        ]

    def deploy_spells(self, frame):
        self._sync_frame_size(frame)
        roi = self.vision.bottom_half_region(frame)
        bx, by = self.vision.find_template(frame, "earthquake.png", region=roi)
        if bx:
            self.input.click(bx, by, pause=0.2)
            offset = int(self.config.get_scaled("earthquake", 400))
            ltr = self._earthquake_anchor_triplet(self._scaled_deployment_data(), offset)
            fh, fw = frame.shape[:2]
            num, den = _EARTHQUAKE_RANDOM_LINE_FROM_BOTTOM
            y_line = self._earthquake_horizontal_y(fh, num, den)

            if self.earthquake_method == EARTHQUAKE_METHOD_RANDOM:
                arc_dense = self._sample_arc_through_three(ltr, _EARTHQUAKE_REGION_ARC_SAMPLES)
                if random.choice((True, False)):
                    arc_dense = arc_dense[::-1]
                poly = self._earthquake_fill_polygon(arc_dense, y_line)
                if abs(self._polygon_double_area(poly)) < 2.0:
                    logger.warning(
                        "Earthquake random region degenerate; using curve placement with jitter."
                    )
                    points = self._earthquake_curve_points_with_jitter(ltr)
                else:
                    points = self._random_points_in_polygon(poly, fw, fh, 11)
            else:
                points = self._earthquake_curve_points_with_jitter(ltr)

            for cx, cy in points:
                jx = max(0, min(fw - 1, cx))
                jy = max(0, min(fh - 1, cy))
                self.input.click_at(jx, jy, rand=False)
                delay = random.uniform(0.1, 0.3)
                if self.stop_event:
                    self.stop_event.wait(delay)
                else:
                    time.sleep(delay)


class TroopSpamStrategy(AttackStrategy):
    def __init__(
        self,
        input_service,
        vision_service,
        config,
        stop_event,
        troop_name: str,
        duration: int,
        status_callback=None,
        earthquake_method: str = EARTHQUAKE_METHOD_CURVE,
    ):
        super().__init__(
            input_service, vision_service, config, stop_event, earthquake_method=earthquake_method
        )
        self.troop_name = troop_name
        self.duration = duration
        self.status_callback = status_callback

    def execute(self, frame, stop_event=None):
        ev = stop_event or self.stop_event
        self._sync_frame_size(frame)
        logger.info(f"Executing {self.troop_name} strategy")

        roi = self.vision.bottom_half_region(frame)
        tx, ty = self.vision.find_template(
            frame, f"{self.troop_name}.png", region=roi
        )
        if tx is None:
            msg = f"Troop {self.troop_name} not found!"
            logger.warning(msg)
            if self.status_callback:
                self.status_callback(msg)
            return False

        # Match hero/siege clicks: no ±15px jitter — bar icons are tight; random misses the card.
        self.input.click(tx, ty, pause=0.3, rand=False)
        if ev and ev.wait(0.2):
            return True

        # Path definition
        corners = ["top", "right", "bottom", "left"]
        # 16:9: spam only begins at left or right edge; otherwise avoid starting at bottom.
        if self.config.aspect_key == ASPECT_16_9:
            start_idx = random.choice([1, 3])
        else:
            start_idx = random.choice([0, 1, 3])
        direction = random.choice([1, -1])  # 1 = CW, -1 = CCW
        
        # Create ordered list of corners: [Start, 2, 3, 4, Start]
        ordered_corners = []
        for i in range(5): # 5 points to close the loop
            idx = (start_idx + (i * direction)) % 4
            ordered_corners.append(corners[idx])

        # Start Deployment (The "Anchor")
        start_corner = ordered_corners[0]
        # We need to track current position for human_move
        curr_x, curr_y = self._expand_loc(*self._point(start_corner))
        
        self.input.mouse_down(curr_x, curr_y)
        if ev and ev.wait(0.65):
            self.input.mouse_up(curr_x, curr_y)
            return True

        try:
            total_duration = self.duration
            segment_duration = total_duration / 4

            for i in range(len(ordered_corners) - 1):
                if ev and ev.is_set():
                    break

                next_c = ordered_corners[i+1]
                target_x, target_y = self._expand_loc(*self._point(next_c))
                duration = random.uniform(segment_duration * 0.9, segment_duration * 1.1)

                self.input.human_move(curr_x, curr_y, target_x, target_y, duration=duration)

                curr_x, curr_y = target_x, target_y

        finally:
            self.input.mouse_up(curr_x, curr_y)

        if ev and ev.is_set():
            return True

        frame = self.input.window_service.screenshot()
        if frame is not None:
            self._sync_frame_size(frame)
            self.deploy_heroes(frame)

            if ev and ev.is_set():
                return True

            frame = self.input.window_service.screenshot()
            if frame is not None:
                self._sync_frame_size(frame)
                self.deploy_spells(frame)
        return True
