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
        heroes = ["queen", "warden", "RC", "king", "prince"]
        random.shuffle(heroes)
        
        deployed_heroes = []

        # Deploy Log Launcher
        lx, ly = self.vision.find_template(frame, "loglauncher.png", threshold=0.7)
        if lx:
            deploy_point = self._get_hero_deploy_point()
            self.input.click(lx, ly, pause=0.2, rand=False)
            self.input.click(*deploy_point, pause=0.2)

        # Loop 1: Deploy Heroes
        for hero in heroes:
            bx, by = self.vision.find_template(frame, f"{hero}.png", threshold=0.7)
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

    def deploy_spells(self, frame):
        bx, by = self.vision.find_template(frame, "earthquake.png")
        if bx:
            self.input.click(bx, by, pause=0.2)
            corners = ["left", "top", "right"]
            random.shuffle(corners)
            
            offset = self.data.get("earthquake", 400)
            
            for corner in corners[:3]:
                cx, cy = self.data[corner]
                if corner == "left": cx += int(offset * 1.3)
                elif corner == "top": cy += offset
                else: cx -= int(offset * 1.3)
                
                for _ in range(4):
                    self.input.click(cx, cy, pause=0.1)


class TroopSpamStrategy(AttackStrategy):
    def __init__(self, input_service, vision_service, config, stop_event, troop_name: str, duration: int):
        super().__init__(input_service, vision_service, config, stop_event)
        self.troop_name = troop_name
        self.duration = duration

    def execute(self, frame, stop_event=None):
        ev = stop_event or self.stop_event
        logger.info(f"Executing {self.troop_name} strategy")

        delay = random.randint(1, 2)
        if ev and ev.wait(delay):
            return

        tx, ty = self.vision.find_template(frame, f"{self.troop_name}.png")
        if not tx:
            logger.warning(f"Troop {self.troop_name} not found!")
            return

        self.input.click(tx, ty)
        if ev and ev.wait(0.2):
            return

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
            return

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
            return

        frame = self.input.window_service.screenshot()
        if frame is not None:
            self.deploy_spells(frame)

            if ev and ev.is_set():
                return

            frame = self.input.window_service.screenshot()
            if frame is not None:
                self.deploy_heroes(frame)
