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
        star_bonus: bool = False,
        status_callback=None,
        multi_run_players: Optional[List[PlayerEntry]] = None,
        ranked_fill: bool = False,
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
            f"Bot started. Method: {method}, Time: {run_time_minutes}m, "
            f"StarBonus: {star_bonus}, MultiRun: {mr}, RankedFill: {ranked_fill}"
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
                    self._run_loop(method, duration, star_bonus, ranked_fill)
                    self._check_stop()
                    self._multi_run_builder_base_after_session()
                    self._check_stop()
            else:
                self._run_loop(method, duration, star_bonus, ranked_fill)
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

    def _update_config_size(self, frame) -> None:
        """Reload aspect profile if screenshot size implies a different template folder."""
        self.config.set_target_size_from_frame(frame)

    def _scroll_point(self) -> Tuple[int, int]:
        """Scroll anchor in authoring space [1000,1000]; scaled to current capture."""
        x, y = self.config.scale_point([1000, 1000])
        return x, y

    def _run_loop(
        self,
        method_id: int,
        duration_seconds: int,
        star_bonus: bool = False,
        ranked_fill: bool = False,
    ):
        start_time = time.time()

        # Initial setup
        if self.stop_event.wait(1):
            return
        frame = self.window.screenshot()
        self._update_config_size(frame)
        empty_pt = self.config.get_point("empty")
        self.input.click(*empty_pt, pause=0.2)

        self.input.scroll(*self._scroll_point(), 20)
        delay = random.uniform(0.1, 0.3)
        if self.stop_event.wait(delay):
            return

        # Star bonus: only farm if empty- or glow-star icon is visible (bonus still to earn/claim).
        if star_bonus and self._is_star_bonus_claimed():
            logger.info(
                "Star bonus mode: no star bonus template matched on home — nothing to collect. Finishing without attacks."
            )
            return

        while time.time() - start_time < duration_seconds:
            self._check_stop()

            # Start Attack
            troop_failed = self._find_match_and_attack(method_id, ranked_fill)

            # Return Home (clicks Okay, then Return Home)
            self._return_home()

            # Recover/Home Check (get to home screen - Attack button visible)
            self._home_screen_recovery()

            # Stop if troop was not found (after completing current cycle)
            if troop_failed:
                break

            # Scroll down/out a bit now that we're on home
            self.input.scroll(*self._scroll_point(), 5)
            if self.stop_event.wait(random.uniform(0.15, 0.25)):
                return

            # Star Bonus mode: stop when neither emptystar nor glowstar matches on home
            if star_bonus and self._is_star_bonus_claimed():
                logger.info("Star bonus claimed (star icons no longer visible). Stopping.")
                break

    def _find_match_and_attack(self, method_id: int, ranked_fill: bool = False) -> bool:
        """Returns True if the bot should stop (troop not found, or ranked limit reached)."""
        # Click Attack
        ax, ay = self._wait_for_image("attack.png")
        if not ax: return False
        self.input.click(ax, ay, pause=0.1)

        # Farm Battle vs Ranked (Find a Match)
        battle_template = "rankedbattle.png" if ranked_fill else "farmbattle.png"
        fx, fy = self._wait_for_image(battle_template)
        if not fx:
            if ranked_fill:
                msg = "Ranked battle button not found — daily limit may be reached. Stopping."
                logger.info(msg)
                cb = getattr(self, "_status_callback", None)
                if cb:
                    cb(msg)
                return True
            return False
        self.input.click(fx, fy, pause=0.1)

        # Valkyrie: verify army / load recipe before confirming attack (attack2.png)
        if method_id == 3 and not self._ensure_valkyrie_army_from_recipes():
            return False

        # Click Attack (Confirm?)
        a2x, a2y = self._wait_for_image("attack2.png")  # Sometimes needed
        if a2x:
            self.input.click(a2x, a2y, pause=0.1)
            if ranked_fill:
                rx, ry = self._wait_for_image("rankedattackconfirm.png", timeout=10)
                if not rx:
                    logger.warning("rankedattackconfirm.png not found after attack2.png")
                else:
                    self.input.click(rx, ry, pause=0.1)

        # Base loaded: in-battle bar shows Surrender or End Battle (never both)
        self._wait_for_any_image(("surrender.png", "endbattle.png"), timeout=30)

        # Base is visible: move cursor to center and nudge view (short wheel) before deploying
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        self.input.move(cx, cy)
        if self.stop_event.wait(0.05):
            return False
        self.input.scroll(cx, cy, 3)

        # Fresh capture after input so strategy sees the settled view
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)

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
        """True if neither emptystar nor glowstar matches strongly (bonus claimed / not shown)."""
        STAR_BONUS_THRESHOLD = 0.75
        frame = self.window.screenshot()
        if frame is None:
            return False
        self._update_config_size(frame)
        for template in ("emptystar.png", "glowstar.png"):
            _, _, confidence = self.vision.find_template_with_confidence(
                frame, template, threshold=0.0
            )
            if confidence >= STAR_BONUS_THRESHOLD:
                return False
        return True

    def _home_screen_recovery(self):
        """Ensures we are back at home screen. Dismisses any Okay popup before considering home."""
        for _ in range(15):
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(1):
                    return
                continue
            self._update_config_size(frame)

            # Check Okay first - dismiss any popup before we consider ourselves home
            ox, oy = self.vision.find_template(frame, "okay.png")
            if ox:
                self.input.click(ox, oy)
                if self.stop_event.wait(0.3):
                    return
                continue

            # No popup; Home Village builder portrait (top half) means we're home
            top_roi = VisionService.top_half_region(frame)
            hx, hy = self.vision.find_template(frame, "builder.png", region=top_roi)
            if hx:
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
        self.input.click(cux, cuy, pause=1.0)

        ucx, ucy = self._wait_for_player_name(
            username,
            timeout=25,
            min_confidence=70,
            tesseract_config="--psm 11",
            match_alnum_only=True,
            fuzzy_min_ratio=0.8,
        )
        if not ucx:
            err = f'Multi-run: could not find username "{username}" on screen (OCR)'
            logger.error(err)
            if cb:
                cb(err)
            raise RuntimeError(err)
        self.input.click(ucx, ucy, pause=0.2)
        if self.stop_event.wait(1.0):
            self._check_stop()

        ax, ay = self._wake_home_and_wait_for_attack(timeout=30)
        if not ax:
            err = (
                f"Multi-run: Home Village not ready after loading {username!r} "
                "(builder.png / attack.png timeout after login / leaving Builder Base)"
            )
            logger.error(err)
            if cb:
                cb(err)
            raise RuntimeError(err)

    def _wake_home_and_wait_for_attack(
        self, timeout: int = 30
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        After switching accounts: dismiss idle UI, then poll the **top half** for village type
        (``mbuilder.png`` = Builder Base, ``builder.png`` = Home Village). If Builder Base,
        leave via :meth:`_leave_builder_base_with_nboat`. When Home Village is detected, return
        ``attack.png`` coordinates from the **bottom half** (battle bar) once visible — same
        template as :meth:`_find_match_and_attack` uses to start battles.
        """
        frame = self.window.screenshot()
        self._update_config_size(frame)
        empty_pt = self.config.get_point("empty")
        self.input.click(*empty_pt, pause=0.2)
        self.input.scroll(*self._scroll_point(), 20)
        delay = random.uniform(0.1, 0.3)
        if self.stop_event.wait(delay):
            return None, None

        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is not None:
                self._update_config_size(frame)
                top_roi = VisionService.top_half_region(frame)
                mx, my = self.vision.find_template(
                    frame, "mbuilder.png", region=top_roi
                )
                if mx:
                    logger.info(
                        "Account loaded in Builder Base (mbuilder.png); leaving to Home Village"
                    )
                    cb = getattr(self, "_status_callback", None)
                    if cb:
                        cb("Multi-run: Builder Base on login — leaving (nboat)")
                    self._leave_builder_base_with_nboat(settle_before_drag=False)
                    if self.stop_event.wait(1.0):
                        return None, None
                    continue

                hx, hy = self.vision.find_template(
                    frame, "builder.png", region=top_roi
                )
                if hx:
                    bot_roi = VisionService.bottom_half_region(frame)
                    ax, ay = self.vision.find_template(
                        frame, "attack.png", region=bot_roi
                    )
                    if ax:
                        return ax, ay

            self.input.click(*empty_pt, pause=0.15)
            if self.stop_event.wait(0.35):
                return None, None
        return None, None

    def _leave_builder_base_with_nboat(self, settle_before_drag: bool = True) -> None:
        """
        Pan down-left from screen center (~500px), then click ``nboat.png`` to return to Home Village.
        Does not check ``mbuilder.png`` first — call only when a BB→HV trip is intended.

        ``settle_before_drag``: small delay after prior UI (e.g. collect clicks) before capturing
        dimensions and dragging.
        """
        self._check_stop()

        if settle_before_drag:
            if self.stop_event.wait(0.75):
                self._check_stop()

        frame = self.window.screenshot()
        if frame is None or frame.size == 0:
            return
        self._update_config_size(frame)

        logger.info("Leaving Builder Base (drag + nboat)")
        cb = getattr(self, "_status_callback", None)
        if cb:
            cb("Multi-run: leaving Builder Base (nboat)")

        self._check_stop()
        h, w = frame.shape[:2]
        cx = w // 2 + random.randint(-25, 25)
        cy = h // 2 + random.randint(-25, 25)
        cx = max(8, min(w - 8, cx))
        cy = max(8, min(h - 8, cy))

        self.input.move(cx, cy, 0)
        self.input.mouse_up(cx, cy)
        if self.stop_event.wait(0.06):
            self._check_stop()

        step = 500
        x2 = max(8, min(w - 8, cx - step))
        y2 = max(8, min(h - 8, cy + step))

        self.input.mouse_down(cx, cy)
        self.input.human_move(cx, cy, x2, y2, duration=random.uniform(0.35, 0.55))
        self.input.mouse_up(x2, y2)

        if self.stop_event.wait(0.45):
            self._check_stop()

        nx, ny = self._wait_for_image("nboat.png", timeout=12, error=False)
        if nx:
            self.input.click(nx, ny, pause=0.25)
        else:
            logger.warning("nboat.png not found after Builder Base drag — may still be in Builder Base")

    def _multi_run_collect_home_village_resources(self) -> None:
        """Multi-run: tap Home Village collect bubbles if visible, before taking the boat to Builder Base."""
        cb = getattr(self, "_status_callback", None)
        logger.info("Multi-run: Home Village collect (hgold, helixir, hdelixir)")
        if cb:
            cb("Multi-run: Home Village collect")
        for tpl in ("hgold.png", "helixir.png", "hdelixir.png"):
            self._check_stop()
            rx, ry = self._find_template_once(tpl, threshold=0.7)
            if rx:
                self.input.click(rx, ry, pause=0.15)

    def _multi_run_builder_base_after_session(self) -> None:
        """
        Multi-run only: after an account's farming session, collect Home Village resources if icons
        appear, open the secondary base via boat, collect builder resources if icons appear,
        optionally run the clock boost chain, then leave Builder Base.
        """
        self._multi_run_collect_home_village_resources()

        cb = getattr(self, "_status_callback", None)
        msg = "Multi-run: Builder Base (boat → collect)"
        logger.info(msg)
        if cb:
            cb(msg)

        bx, by = self._wait_for_image("boat.png", timeout=15, error=False)
        if not bx:
            logger.warning("Multi-run: boat.png not found — skipping Builder Base step")
            return

        self.input.click(bx, by, pause=0.2)
        if self.stop_event.wait(1.0):
            self._check_stop()

        for tpl in ("bgold.png", "belixir.png", "bgem.png"):
            self._check_stop()
            rx, ry = self._find_template_once(tpl, threshold=0.7)
            if rx:
                self.input.click(rx, ry, pause=0.15)

        self._check_stop()
        cx, cy = self._wait_for_image("bclock.png", timeout=2, error=False)
        if cx:
            self.input.click(cx, cy, pause=0.2)
            if self.stop_event.wait(1.0):
                self._check_stop()

            cbx, cby = self._wait_for_image("clockboost.png", timeout=10, error=False)
            if cbx:
                self.input.click(cbx, cby, pause=0.2)
            if self.stop_event.wait(1.0):
                self._check_stop()

            bux, buy = self._wait_for_image("boost.png", timeout=10, error=False)
            if bux:
                self.input.click(bux, buy, pause=0.15)

        self._leave_builder_base_with_nboat(settle_before_drag=True)

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

        OCR is limited to the right half of the window unless ``region`` is passed explicitly.
        """
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                if self.stop_event.wait(0.5):
                    return None, None
                continue
            self._update_config_size(frame)
            roi = region if region is not None else VisionService.right_half_region(frame)
            x, y = self.vision.find_word_on_screen(frame, text, region=roi, **ocr_kwargs)
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
            self._update_config_size(frame)
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

    def _search_region_for_template(
        self,
        frame,
        template: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        y_anchor: Optional[int] = None,
        y_slop: int = 200,
    ) -> Optional[Tuple[int, int, int, int]]:
        if region is not None:
            return region
        if y_anchor is not None:
            h, w = frame.shape[:2]
            y0 = max(0, y_anchor - y_slop)
            y1 = min(h, y_anchor + y_slop)
            return (0, y0, w, y1 - y0)
        if template in BOTTOM_HALF_BOT_TEMPLATES:
            return VisionService.bottom_half_region(frame)
        return None

    def _find_template_once(
        self,
        template: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        y_anchor: Optional[int] = None,
        y_slop: int = 200,
        threshold: float = 0.8,
    ) -> Tuple[Optional[int], Optional[int]]:
        """One screenshot; match template or return (None, None). No polling."""
        self._check_stop()
        frame = self.window.screenshot()
        if frame is None:
            return None, None
        self._update_config_size(frame)
        search_region = self._search_region_for_template(
            frame, template, region, y_anchor, y_slop
        )
        return self.vision.find_template(
            frame, template, threshold=threshold, region=search_region
        )

    def _wait_for_any_image(
        self,
        templates: Tuple[str, ...],
        timeout: int = 10,
        error: bool = True,
        threshold: float = 0.8,
    ) -> Tuple[Optional[int], Optional[int]]:
        """First match among `templates` wins (same frame); order only matters if both match."""
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                continue
            self._update_config_size(frame)
            for template in templates:
                search_region = self._search_region_for_template(
                    frame, template, None, None, 200
                )
                x, y = self.vision.find_template(
                    frame, template, threshold=threshold, region=search_region
                )
                if x:
                    return x, y
            if self.stop_event.wait(0.5):
                return None, None
        if error:
            logger.warning(f"Timeout waiting for any of {templates}")
        return None, None

    def _wait_for_image(
        self,
        template: str,
        timeout: int = 10,
        error: bool = True,
        region: Optional[Tuple[int, int, int, int]] = None,
        y_anchor: Optional[int] = None,
        y_slop: int = 200,
        threshold: float = 0.8,
    ) -> Tuple[Optional[int], Optional[int]]:
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            frame = self.window.screenshot()
            if frame is None:
                continue
            self._update_config_size(frame)

            search_region = self._search_region_for_template(
                frame, template, region, y_anchor, y_slop
            )
            x, y = self.vision.find_template(
                frame, template, threshold=threshold, region=search_region
            )
            if x:
                return x, y
            if self.stop_event.wait(0.5):
                return None, None

        if error:
            logger.warning(f"Timeout waiting for {template}")
        return None, None
