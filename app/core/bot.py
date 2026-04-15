import time
import random
import threading
from typing import List, Optional, Tuple

from app.config import Config
from app.core.strategies import TroopSpamStrategy
from app.services.input import InputService
from app.services.vision import VisionService, BOTTOM_HALF_BOT_TEMPLATES
from app.services.window import WindowService
from app.utils.logger import setup_logger
from app.utils.player_list_store import PlayerEntry

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

    def start(
        self,
        method: int,
        run_time_minutes: int,
        upgrade_walls: bool,
        star_bonus: bool = False,
        status_callback=None,
        multi_run_players: Optional[List[PlayerEntry]] = None,
    ):
        """Starts the bot loop. With ``multi_run_players``, runs a full session per enabled player."""
        self._status_callback = status_callback
        # Re-find window each time farming starts (hwnd changes when game is closed/reopened)
        if not self.window.find_window():
            raise RuntimeError("Clash of Clans window not found. Please ensure the game is open.")

        self.running = True
        self.stop_event.clear()

        duration = 900 if star_bonus else run_time_minutes * 60  # 15 min hard cap for star bonus
        mr = multi_run_players is not None
        logger.info(
            f"Bot started. Method: {method}, Time: {run_time_minutes}m, Walls: {upgrade_walls}, "
            f"StarBonus: {star_bonus}, MultiRun: {mr}"
        )

        try:
            if multi_run_players is not None:
                queue = [p for p in multi_run_players if p.enabled]
                if not queue:
                    raise RuntimeError("Multi-run: no players marked Run")
                for player in queue:
                    self._check_stop()
                    self._switch_account_and_load_home(player.name)
                    self._check_stop()
                    self._run_loop(method, duration, upgrade_walls, star_bonus)
                    self._check_stop()
            else:
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

        # Star bonus: only farm if the empty-star icon is visible (bonus still to earn/claim).
        if star_bonus and self._is_star_bonus_claimed():
            logger.info(
                "Star bonus mode: emptystar.png not found on home — nothing to collect. Finishing without attacks."
            )
            return

        while time.time() - start_time < duration_seconds:
            self._check_stop()

            if upgrade_walls:
                self._handle_walls()

            # Start Attack
            troop_failed = self._find_match_and_attack(method_id)

            # Return Home (clicks Okay, then Return Home)
            self._return_home()

            # Recover/Home Check (get to home screen - Attack button visible)
            self._home_screen_recovery()

            # Stop if troop was not found (after completing current cycle)
            if troop_failed:
                break

            # Scroll down/out a bit now that we're on home
            self.input.scroll(1000, 1000, 5)
            if self.stop_event.wait(random.uniform(0.15, 0.25)):
                return

            # Star Bonus mode: stop when emptystar.png is NOT found on home screen
            # (empty star gone = star bonus claimed)
            if star_bonus and self._is_star_bonus_claimed():
                logger.info("Star bonus claimed (empty star no longer visible). Stopping.")
                break

    def _find_match_and_attack(self, method_id: int) -> bool:
        """Returns True if troop was not found (bot should stop)."""
        # Click Attack
        ax, ay = self._wait_for_image("attack.png")
        if not ax: return False
        self.input.click(ax, ay, pause=0.1)

        # Click Find Match
        fx, fy = self._wait_for_image("findmatch.png")
        if not fx: return False
        self.input.click(fx, fy, pause=0.1)

        # Valkyrie: verify army / load recipe before confirming attack (attack2.png)
        if method_id == 3 and not self._ensure_valkyrie_army_from_recipes():
            return False

        # Click Attack (Confirm?)
        a2x, a2y = self._wait_for_image("attack2.png")  # Sometimes needed
        if a2x:
            self.input.click(a2x, a2y, pause=0.1)

        # Wait for "Find" screen (clouds) to disappear -> Base found
        # Actually logic is: wait until "find.png" (Next button) is visible
        self._wait_for_image("find.png", timeout=30)

        # Execute Strategy
        frame = self.window.screenshot()
        if frame is None: return False

        strategy = self._get_strategy(method_id)
        result = strategy.execute(frame, self.stop_event)
        
        # Wait for battle end
        self._wait_for_battle_end(is_sneaky=(method_id == 1))
        return result is False

    def _get_strategy(self, method_id: int):
        cb = getattr(self, "_status_callback", None)
        if method_id == 1:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "sneaky", 15, status_callback=cb)
        elif method_id == 2:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "superminion", 3.1, status_callback=cb)
        elif method_id == 3:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "valkyrie", 5.5, status_callback=cb)
        else:
            return TroopSpamStrategy(self.input, self.vision, self.config, self.stop_event, "sneaky", 15, status_callback=cb)

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
        """True if emptystar.png is absent or weak match (bonus already claimed / not available)."""
        EMPTYSTAR_THRESHOLD = 0.75
        frame = self.window.screenshot()
        if frame is None:
            return False
        _, _, confidence = self.vision.find_template_with_confidence(
            frame, "emptystar.png", threshold=0.0
        )
        return confidence < EMPTYSTAR_THRESHOLD

    def _home_screen_recovery(self):
        """Ensures we are back at home screen. Dismisses any Okay popup before considering home."""
        for _ in range(15):
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(1):
                    return
                continue

            # Check Okay first - dismiss any popup before we consider ourselves home
            ox, oy = self.vision.find_template(frame, "okay.png")
            if ox:
                self.input.click(ox, oy)
                if self.stop_event.wait(0.3):
                    return
                continue

            # No popup; if we see Attack button, we are home (bar is bottom half)
            roi = VisionService.bottom_half_region(frame)
            ax, ay = self.vision.find_template(frame, "attack.png", region=roi)
            if ax:
                return

            if self.stop_event.wait(1):
                return

    def _switch_account_and_load_home(self, username: str) -> None:
        """Open Settings → Change user, OCR-click username, wait for home. Raises on failure."""
        cb = getattr(self, "_status_callback", None)
        msg = f"Multi-run: switching to {username!r}"
        logger.info(msg)
        if cb:
            cb(msg)

        stx, sty = self._wait_for_image("settings.png")
        if not stx:
            raise RuntimeError("Multi-run: settings button not found")
        self.input.click(stx, sty, pause=0.25)

        cux, cuy = self._wait_for_image("changeuser.png")
        if not cux:
            raise RuntimeError("Multi-run: change user button not found")
        self.input.click(cux, cuy, pause=0.25)

        ucx, ucy = self._wait_for_player_name(
            username,
            timeout=25,
            min_confidence=25,
            tesseract_config="--psm 11",
        )
        if not ucx:
            err = f'Multi-run: could not find username "{username}" on screen (OCR)'
            logger.error(err)
            if cb:
                cb(err)
            raise RuntimeError(err)
        self.input.click(ucx, ucy, pause=0.2)

        ax, ay = self._wake_home_and_wait_for_attack(timeout=30)
        if not ax:
            err = f"Multi-run: home not ready after loading {username!r} (attack.png timeout)"
            logger.error(err)
            if cb:
                cb(err)
            raise RuntimeError(err)

    def _wake_home_and_wait_for_attack(
        self, timeout: int = 30
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        After switching accounts: same idea as session start — click bottom, scroll once, then
        repeatedly click the empty / bottom area while scanning the lower half for attack.png.
        """
        empty_pt = self.config.get_point("empty")
        self.input.click(*empty_pt, pause=0.2)
        self.input.scroll(1000, 1000, 20)
        delay = random.uniform(0.1, 0.3)
        if self.stop_event.wait(delay):
            return None, None

        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is not None:
                roi = VisionService.bottom_half_region(frame)
                ax, ay = self.vision.find_template(frame, "attack.png", region=roi)
                if ax:
                    return ax, ay
            self.input.click(*empty_pt, pause=0.15)
            if self.stop_event.wait(0.35):
                return None, None
        return None, None

    def _frame_shows_supercell_login_prompt(self, frame) -> bool:
        """True if OCR sees the Supercell ID login line (list scroll won't help)."""
        if frame is None or frame.size == 0:
            return False
        words = self.vision.find_words_ocr(
            frame,
            query=None,
            min_confidence=20,
            preprocess=True,
            tesseract_config="--psm 11",
        )
        blob = " ".join(w.text for w in words).lower()
        if "supercell id" in blob:
            return True
        if "log in" in blob and "supercell" in blob:
            return True
        return False

    def _scroll_player_list_with_drag(self, frame) -> None:
        """Drag ~200px upward from lower-right (client coords) to scroll the change-user list."""
        if frame is None or frame.size == 0:
            return
        h, w = frame.shape[:2]
        x1 = int(w * 0.86) + random.randint(-15, 15)
        x1 = max(int(w * 0.72), min(w - 8, x1))
        y1 = int(h * 0.86) + random.randint(-12, 12)
        y1 = max(int(h * 0.55), min(h - 12, y1))
        y2 = max(int(h * 0.12), y1 - 200)
        x2 = x1
        self.input.mouse_down(x1, y1)
        self.input.human_move(x1, y1, x2, y2, duration=random.uniform(0.28, 0.42))
        self.input.mouse_up(x2, y2)

    def _wait_for_player_name(
        self,
        text: str,
        timeout: int = 25,
        error: bool = True,
        region: Optional[Tuple[int, int, int, int]] = None,
        **ocr_kwargs,
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Like :meth:`_wait_for_text`, but after each failed OCR pass drags upward in the lower-right
        to scroll the account list before trying again.
        """
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return None, None
                continue
            x, y = self.vision.find_word_on_screen(frame, text, region=region, **ocr_kwargs)
            if x:
                return x, y
            if self._frame_shows_supercell_login_prompt(frame):
                msg = (
                    f'Multi-run: "Log in to Supercell ID" is showing and {text!r} was not found — '
                    "log in or dismiss that screen, then retry."
                )
                logger.warning(msg)
                cb = getattr(self, "_status_callback", None)
                if cb:
                    cb(msg)
                raise RuntimeError(msg)
            self._scroll_player_list_with_drag(frame)
            if self.stop_event.wait(0.45):
                return None, None
        if error:
            logger.warning(f"Timeout waiting for player name OCR match: {text!r}")
        return None, None

    def _wait_for_text(
        self,
        text: str,
        timeout: int = 10,
        error: bool = True,
        region: Optional[Tuple[int, int, int, int]] = None,
        **ocr_kwargs,
    ) -> Tuple[Optional[int], Optional[int]]:
        """Poll screenshots until OCR finds ``text`` (substring match). Returns click center."""
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return None, None
                continue
            x, y = self.vision.find_word_on_screen(frame, text, region=region, **ocr_kwargs)
            if x:
                return x, y
            if self.stop_event.wait(0.5):
                return None, None
        if error:
            logger.warning(f"Timeout waiting for OCR text containing {text!r}")
        return None, None

    def _ensure_valkyrie_army_from_recipes(self) -> bool:
        """If Valkyrie army template is missing, load it from Saved Recipes. Returns False on failure."""
        vx, vy = self._wait_for_image("valkarmy.png", timeout=3, error=False)
        if vx:
            return True

        sx, sy = self._wait_for_image("savedrecipes.png")
        if not sx:
            logger.warning("Saved Recipes button not found while ensuring Valkyrie army")
            return False
        self.input.click(sx, sy, pause=0.2)

        rx, ry = self._wait_for_image("valkrecipe.png")
        if not rx:
            logger.warning("Valkyrie recipe template not found")
            return False

        ux, uy = self._wait_for_image("use.png", y_anchor=ry, y_slop=200)
        if not ux:
            logger.warning("Use button not found near Valkyrie recipe row")
            return False
        self.input.click(ux, uy, pause=0.2)

        if self.stop_event.wait(0.35):
            return False
        vx2, _ = self._wait_for_image("valkarmy.png", timeout=5, error=False)
        if not vx2:
            logger.warning("valkarmy.png still not visible after applying saved recipe")
            return False
        return True

    def _wait_for_image(
        self,
        template: str,
        timeout: int = 10,
        error: bool = True,
        region: Optional[Tuple[int, int, int, int]] = None,
        y_anchor: Optional[int] = None,
        y_slop: int = 200,
    ) -> Tuple[Optional[int], Optional[int]]:
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                continue

            if region is not None:
                search_region = region
            elif y_anchor is not None:
                h, w = frame.shape[:2]
                y0 = max(0, y_anchor - y_slop)
                y1 = min(h, y_anchor + y_slop)
                search_region = (0, y0, w, y1 - y0)
            elif template in BOTTOM_HALF_BOT_TEMPLATES:
                search_region = VisionService.bottom_half_region(frame)
            else:
                search_region = None

            x, y = self.vision.find_template(frame, template, region=search_region)
            if x:
                return x, y
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
