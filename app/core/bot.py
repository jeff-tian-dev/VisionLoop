import time
import random
import threading
from typing import Optional, Callable, Tuple
from app.config import Config
from app.services.window import WindowService
from app.services.input import InputService
from app.services.vision import VisionService
from app.core.strategies import TroopSpamStrategy
from app.utils.logger import setup_logger

logger = setup_logger("BotCore")

class Bot:
    """Main Bot Logic."""
    
    def __init__(self):
        self.config = Config()
        self.window = WindowService()
        self.stop_event = threading.Event()
        self.input = InputService(self.window, self.stop_event)
        self.vision = VisionService()
        self.running = False

    def start(self, method: int, run_time_minutes: int, upgrade_walls: bool, star_bonus: bool = False):
        """Starts the bot loop."""
        # Re-find window each time farming starts (hwnd changes when game is closed/reopened)
        if not self.window.find_window():
            raise RuntimeError("Clash of Clans window not found. Please ensure the game is open.")

        self.running = True
        self.stop_event.clear()

        duration = 300 if star_bonus else run_time_minutes * 60  # 5 min for star bonus
        logger.info(f"Bot started. Method: {method}, Time: {run_time_minutes}m, Walls: {upgrade_walls}, StarBonus: {star_bonus}")

        try:
            self._run_loop(method, duration, upgrade_walls, star_bonus)
        except InterruptedError:
            pass
        except Exception as e:
            logger.error(f"Bot crashed: {e}", exc_info=True)
            raise
        finally:
            self.running = False
            logger.info("Bot stopped.")

    def stop(self):
        """Signals the bot to stop."""
        self.running = False
        self.stop_event.set()

    def _check_stop(self):
        if self.stop_event.is_set():
            raise InterruptedError("Bot stopped by user")

    def _run_loop(self, method_id: int, duration_seconds: int, upgrade_walls: bool, star_bonus: bool = False):
        start_time = time.time()

        # Initial setup
        if self.stop_event.wait(1):
            return
        empty_pt = self.config.get_point("empty")
        self.input.click(*empty_pt, pause=0.2)

        self.input.scroll(1000, 1000, 20)
        delay = random.uniform(0.1, 0.3)
        if self.stop_event.wait(delay):
            return

        while time.time() - start_time < duration_seconds:
            self._check_stop()

            if upgrade_walls:
                self._handle_walls()

            # Start Attack
            self._find_match_and_attack(method_id)

            # Return Home (clicks Okay, then Return Home)
            self._return_home()

            # Recover/Home Check (get to home screen - Attack button visible)
            self._home_screen_recovery()

            # Star Bonus mode: stop when emptystar.png is NOT found on home screen
            # (empty star gone = star bonus claimed)
            if star_bonus and self._is_star_bonus_claimed():
                logger.info("Star bonus claimed (empty star no longer visible). Stopping.")
                break

    def _find_match_and_attack(self, method_id: int):
        # Click Attack
        ax, ay = self._wait_for_image("attack.png")
        if not ax: return
        self.input.click(ax, ay, pause=0.1)

        # Click Find Match
        fx, fy = self._wait_for_image("findmatch.png")
        if not fx: return
        self.input.click(fx, fy, pause=0.1)
        
        # Click Attack (Confirm?)
        a2x, a2y = self._wait_for_image("attack2.png") # Sometimes needed
        if a2x: self.input.click(a2x, a2y, pause=0.1)

        # Wait for "Find" screen (clouds) to disappear -> Base found
        # Actually logic is: wait until "find.png" (Next button) is visible
        self._wait_for_image("find.png", timeout=30)
        
        # Execute Strategy
        frame = self.window.screenshot()
        if frame is None: return

        strategy = self._get_strategy(method_id)
        strategy.execute(frame, self.stop_event)
        
        # Wait for battle end
        self._wait_for_battle_end(is_sneaky=(method_id == 1))

    def _get_strategy(self, method_id: int):
        if method_id == 1:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "sneaky", 15)
        elif method_id == 2:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "superminion", 3.1)
        elif method_id == 3:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "valkyrie", 5.5)
        else:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "sneaky", 15)

    def _wait_for_battle_end(self, is_sneaky: bool):
        if is_sneaky:
            if self.stop_event.wait(3):
                return
            # Try to find surrender first (most common for sneaky farming)
            sx, sy = self._wait_for_image("surrender.png", timeout=2, error=False)
            if sx: 
                self.input.click(sx, sy, pause=0.1)
            else:
                # If no surrender, maybe we got 50% or TH? Check endbattle
                bx, by = self._wait_for_image("endbattle.png", timeout=2, error=False)
                if bx: self.input.click(bx, by, pause=0.1)
        else:
            bx, by = self._wait_for_image("endbattle.png", timeout=60, error=False)
            if bx:
                self.input.click(bx, by, pause=0.1)
            else:
                # Surrender if end battle not found
                sx, sy = self._wait_for_image("surrender.png", timeout=2, error=False)
                if sx: self.input.click(sx, sy, pause=0.1)

    def _return_home(self) -> bool:
        """Returns True if Okay was found and clicked."""
        ox, oy = self._wait_for_image("okay.png", timeout=10)
        if ox:
            self.input.click(ox, oy, pause=0.1)

        rx, ry = self._wait_for_image("returnhome.png", timeout=10)
        if rx:
            self.input.click(rx, ry, pause=0.1)

        return ox is not None

    def _is_star_bonus_claimed(self) -> bool:
        """Returns True if emptystar.png is NOT found on home screen (star bonus claimed)."""
        EMPTYSTAR_THRESHOLD = 0.75
        frame = self.window.screenshot()
        if frame is None:
            return False
        _, _, confidence = self.vision.find_template_with_confidence(
            frame, "emptystar.png", threshold=0.0
        )
        return confidence < EMPTYSTAR_THRESHOLD

    def _home_screen_recovery(self):
        """Ensures we are back at home screen."""
        for _ in range(15):
            self._check_stop()
            # If we see Attack button, we are home
            ax, ay = self.vision.find_template(self.window.screenshot(), "attack.png")
            if ax: return
            
            # If we see Okay button, click it
            ox, oy = self.vision.find_template(self.window.screenshot(), "okay.png")
            if ox:
                self.input.click(ox, oy)
                if self.stop_event.wait(0.3):
                    return

            if self.stop_event.wait(1):
                return

    def _wait_for_image(self, template: str, timeout: int = 10, error: bool = True) -> Tuple[Optional[int], Optional[int]]:
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None: continue
            
            x, y = self.vision.find_template(frame, template)
            if x: return x, y
            if self.stop_event.wait(0.5):
                return None, None
            
        if error:
            logger.warning(f"Timeout waiting for {template}")
        return None, None

    def _handle_walls(self):
        # Simplified wall logic placeholder - full logic was very complex and specific
        # Implementing basic check to see if resources are full
        frame = self.window.screenshot()
        if frame is None: return
        
        # Check resources (Gold/Elixir)
        # This requires precise pixel checking from original code
        # For now, we skip complex wall logic to ensure core stability first
        pass
