import math
import time
import random
from typing import List, Tuple
from app.services.input import InputService
from app.services.vision import VisionService
from app.services.window import WindowService
from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger("Strategies")

class AttackStrategy:
    """Base class for attack strategies."""

    def __init__(self, input_service: InputService, vision_service: VisionService, config: Config, stop_event=None):
        self.input = input_service
        self.vision = vision_service
        self.config = config
        self.stop_event = stop_event
        self.data = config.data
        self.CORNER_ORDER = ["left", "top", "right", "bottom"]

    def execute(self, frame, stop_event=None):
        raise NotImplementedError

    def _check_stop(self):
        if self.stop_event and self.stop_event.is_set():
            raise InterruptedError("Bot stopped by user")

    def _expand_loc(self, x: int, y: int) -> Tuple[int, int]:
        return x + random.randint(-10, 10), y + random.randint(-10, 10)

    def _corner_helper(self, current: str, direction: int) -> str:
        idx = self.CORNER_ORDER.index(current)
        if direction == 1:
            return self.CORNER_ORDER[(idx + 1) % len(self.CORNER_ORDER)]
        elif direction == 2:
            return self.CORNER_ORDER[(idx - 1) % len(self.CORNER_ORDER)]
        return current

    def _troop_spam_helper(self, corner: str, direction: int, iteration: int, duration: int):
        if iteration == 4:
            return
        
        current_pos = self.data[corner]
        next_corner = self._corner_helper(corner, direction)
        target = self.data[next_corner]
        
        # Move from current corner to next corner
        x1, y1 = self._expand_loc(*current_pos)
        x2, y2 = target # Target is usually a fixed point in config
        
        self.input.human_move(x1, y1, x2, y2, duration)
        
        # Recursive call for next leg
        self._troop_spam_helper(next_corner, direction, iteration + 1, duration)

    def deploy_heroes(self, frame):
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
            deploy_point = self._get_hero_deploy_point()
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
            deploy_point = self._get_hero_deploy_point()
            
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

    def _get_hero_deploy_point(self):
        # Pick a random line between corners
        c_name = random.choice(["top", "right", "left"])
        c1 = self.data[c_name]
        
        if c_name in ["left", "right"]:
            c2 = self.data["top"]
        else:
            c2 = self.data[random.choice(["left", "right"])]
            
        t = random.uniform(0, 1)
        x = c1[0] + (c2[0] - c1[0]) * t
        y = c1[1] + (c2[1] - c1[1]) * t
        return int(x), int(y)

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

    def deploy_spells(self, frame):
        roi = self.vision.bottom_half_region(frame)
        bx, by = self.vision.find_template(frame, "earthquake.png", region=roi)
        if bx:
            self.input.click(bx, by, pause=0.2)
            offset = int(self.data.get("earthquake", 400))
            ltr = self._earthquake_anchor_triplet(self.data, offset)
            points = self._sample_arc_through_three(ltr, 11)
            if random.choice((True, False)):
                points.reverse()
            eq_pause_base = 0.1
            jitter_px = 30
            for cx, cy in points:
                jx = cx + random.randint(-jitter_px, jitter_px)
                jy = cy + random.randint(-jitter_px, jitter_px)
                self.input.click_at(jx, jy, rand=False)
                delay = eq_pause_base * random.uniform(0.7, 1.3)
                if self.stop_event:
                    self.stop_event.wait(delay)
                else:
                    time.sleep(delay)


class TroopSpamStrategy(AttackStrategy):
    def __init__(self, input_service, vision_service, config, stop_event, troop_name: str, duration: int, status_callback=None):
        super().__init__(input_service, vision_service, config, stop_event)
        self.troop_name = troop_name
        self.duration = duration
        self.status_callback = status_callback

    def execute(self, frame, stop_event=None):
        ev = stop_event or self.stop_event
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
        # Avoid starting at bottom (index 2) to prevent UI interference
        start_idx = random.choice([0, 1, 3])
        direction = random.choice([1, -1]) # 1 = CW, -1 = CCW
        
        # Create ordered list of corners: [Start, 2, 3, 4, Start]
        ordered_corners = []
        for i in range(5): # 5 points to close the loop
            idx = (start_idx + (i * direction)) % 4
            ordered_corners.append(corners[idx])

        # Start Deployment (The "Anchor")
        start_corner = ordered_corners[0]
        # We need to track current position for human_move
        curr_x, curr_y = self._expand_loc(*self.data[start_corner])
        
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
                target_x, target_y = self._expand_loc(*self.data[next_c])
                duration = random.uniform(segment_duration * 0.9, segment_duration * 1.1)

                self.input.human_move(curr_x, curr_y, target_x, target_y, duration=duration)

                curr_x, curr_y = target_x, target_y

        finally:
            self.input.mouse_up(curr_x, curr_y)

        if ev and ev.is_set():
            return True

        frame = self.input.window_service.screenshot()
        if frame is not None:
            self.deploy_heroes(frame)

            if ev and ev.is_set():
                return True

            frame = self.input.window_service.screenshot()
            if frame is not None:
                self.deploy_spells(frame)
        return True
