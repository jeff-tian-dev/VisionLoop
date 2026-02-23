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
    
    def __init__(self, input_service: InputService, vision_service: VisionService, config: Config):
        self.input = input_service
        self.vision = vision_service
        self.config = config
        self.data = config.data
        self.CORNER_ORDER = ["left", "top", "right", "bottom"]

    def execute(self, frame):
        raise NotImplementedError

    def _expand_loc(self, x: int, y: int) -> Tuple[int, int]:
        return x + random.randint(-15, 15), y + random.randint(-15, 15)

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
        heroes.append("loglauncher")
        
        deployed_heroes = []

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
            
            if hero != "loglauncher":
                deployed_heroes.append((bx, by))

        # Activate abilities
        for (hx, hy) in deployed_heroes:
            self.input.click(hx, hy, pause=0.2)
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
    def __init__(self, input_service, vision_service, config, troop_name: str, duration: int):
        super().__init__(input_service, vision_service, config)
        self.troop_name = troop_name
        self.duration = duration

    def execute(self, frame):
        logger.info(f"Executing {self.troop_name} strategy")
        time.sleep(random.randint(1, 2))
        
        # Select Troop
        tx, ty = self.vision.find_template(frame, f"{self.troop_name}.png")
        if not tx:
            logger.warning(f"Troop {self.troop_name} not found!")
            return

        self.input.click(tx, ty)
        time.sleep(0.2)
        
        starting_corner = random.choice(["right", "left"])
        start_pos = self.data[starting_corner]
        
        # Start dragging
        sx, sy = self._expand_loc(*start_pos)
        self.input.mouse_down(sx, sy)
        time.sleep(0.7)
        
        try:
            self._troop_spam_helper(starting_corner, random.randint(1, 2), 0, self.duration)
        finally:
            # Ensure mouse up
            self.input.mouse_up(*self._expand_loc(*start_pos))

        # Deploy rest
        # Refresh frame before deploying spells/heroes to ensure we have latest state
        frame = self.input.window_service.screenshot()
        if frame is not None:
            self.deploy_spells(frame)
            
            # Refresh again before heroes just in case
            frame = self.input.window_service.screenshot()
            if frame is not None:
                self.deploy_heroes(frame)
