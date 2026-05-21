from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
import winsound
from typing import Any, List, Optional

import customtkinter as ctk
from tkinter import messagebox

from app.config import check_game_window_aspect_for_start
from app.core.bot import Bot
from app.services.license import LicenseManager, LicenseState, load_saved_key
from app.services.trial import (
    TRIAL_HEARTBEAT_INTERVAL_MS,
    TRIAL_TOTAL_SECONDS,
    TrialResult,
    fetch_trial_status,
    send_trial_heartbeat,
)
from app.ui import theme as t
from app.ui.dialogs import (
    LicenseKeyDialog,
    PlayerListDialog,
    ProfileSettingsDialog,
    RankedAttackConfirmDialog,
)
from app.ui.widgets import (
    Tooltip,
    card,
    neutral_button,
    primary_button,
    danger_button,
    section_title,
    small_chip_button,
    StatusDot,
    format_license_expires_on_line,
    format_trial_expires_in_minutes,
)
from app.utils.common import get_autoloot_log_path
from app.utils.logger import setup_logger
from app.utils.player_list_store import PlayerEntry, load_players
from app.utils.profile_settings_store import load_profile_settings

logger = setup_logger("GUI")

if platform.system() == "Windows":
    try:
        from app.services.taskbar_thumb import TaskbarThumb
    except ImportError:
        TaskbarThumb = None
else:
    TaskbarThumb = None


class AutoLootApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Clash AutoLoot Bot")
        self.resizable(False, False)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.bot = Bot()
        self.bot_thread: Optional[threading.Thread] = None
        self._taskbar_thumb: Any = None
        self._license_dialog: Any = None

        self._trial_remaining_seconds: Optional[int] = None
        self._trial_last_mono: float = 0.0
        self._trial_tick_job: Optional[str] = None
        self._trial_session: int = 0
        self._trial_probe_pending: bool = False

        from app import __version__

        self._license_mgr = LicenseManager(bot_version=__version__)
        self._license_mgr.set_on_state_change(self._on_license_state_change)

        self._build_ui()

        saved_key = load_saved_key()
        self._license_mgr.start(saved_key)
        self._refresh_license_visuals(self._license_mgr.state)
        self.after(1000, self._schedule_trial_balance_probe)

        if TaskbarThumb:
            self.after(500, self._setup_taskbar_thumb)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.configure(fg_color=t.COLOR_APP_BG)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew", padx=t.PAD_OUTER, pady=(t.PAD_OUTER, 0))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=0)

        self._build_header(main)
        self._build_license_strip(main)
        left_col = self._build_left_column(main)
        self._build_attack_card(left_col)
        self._build_schedule_card(left_col)
        self._build_modes_card(left_col)
        self._build_controls_card(left_col)
        self._build_status_bar()

    def _build_header(self, main: ctk.CTkFrame) -> None:
        header = ctk.CTkLabel(
            main,
            text="Clash AutoLoot",
            font=ctk.CTkFont(size=t.FONT_TITLE, weight="bold"),
            text_color=t.COLOR_TEXT,
        )
        header.grid(row=0, column=0, sticky="w", pady=(0, t.PAD_OUTER))

    def _build_license_strip(self, main: ctk.CTkFrame) -> None:
        card_license = card(main)
        card_license.grid(row=1, column=0, sticky="ew", pady=(0, t.CARD_GAP))

        lic_strip = ctk.CTkFrame(card_license, fg_color="transparent")
        lic_strip.grid(row=0, column=0, sticky="ew", padx=t.CARD_PAD, pady=t.CARD_PAD)
        lic_strip.grid_columnconfigure(1, weight=1)

        self._main_lic_dot = StatusDot(lic_strip, bg="#1a1a1a")
        self._main_lic_dot.grid(row=0, column=0, padx=(0, t.SPACE_MD))
        Tooltip(self._main_lic_dot.canvas, self._license_indicator_tooltip_text)

        neutral_button(
            lic_strip,
            text="License key…",
            command=self._open_license_dialog,
            width=118,
            height=t.H_SM,
        ).grid(row=0, column=2, sticky="e")

        self._main_expiry_strip_label = ctk.CTkLabel(
            lic_strip,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=t.COLOR_TEXT_MUTED,
            anchor="w",
        )

    def _build_left_column(self, main: ctk.CTkFrame) -> ctk.CTkFrame:
        left_col = ctk.CTkFrame(main, fg_color="transparent")
        left_col.grid(row=2, column=0, sticky="nsew", padx=(0, t.SPACE_MD))
        left_col.grid_columnconfigure(0, weight=1)
        return left_col

    def _build_attack_card(self, left_col: ctk.CTkFrame) -> None:
        card_attack = card(left_col)
        card_attack.grid(row=0, column=0, sticky="ew", pady=(0, t.CARD_GAP))
        card_attack.grid_columnconfigure(0, weight=1)

        attack_title_row = ctk.CTkFrame(card_attack, fg_color="transparent")
        attack_title_row.grid(row=0, column=0, sticky="ew", padx=t.CARD_PAD, pady=(t.CARD_PAD, t.SPACE_SM))
        attack_title_row.grid_columnconfigure(0, weight=1)

        section_title(attack_title_row, "Attack Strategy").grid(row=0, column=0, sticky="w")
        neutral_button(
            attack_title_row,
            text="Settings",
            command=self._open_profile_settings,
            width=104,
            height=t.H_SM,
            font=ctk.CTkFont(size=t.ATTACK_SECTION_FONT),
        ).grid(row=0, column=1, sticky="e")

        self.attack_choice = ctk.CTkSegmentedButton(
            card_attack,
            values=["Valkyries", "Sneaky Goblins", "Super Minions"],
            font=ctk.CTkFont(size=t.ATTACK_SECTION_FONT),
            height=t.ATTACK_SEGMENTED_HEIGHT,
            command=lambda _: None,
        )
        self.attack_choice.set("Valkyries")
        self.attack_choice.grid(
            row=1, column=0, sticky="ew", padx=t.CARD_PAD, pady=(0, t.CARD_PAD)
        )

    def _build_schedule_card(self, left_col: ctk.CTkFrame) -> None:
        card_schedule = card(left_col)
        card_schedule.grid(row=1, column=0, sticky="ew", pady=(0, t.CARD_GAP))
        card_schedule.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(card_schedule, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=t.CARD_PAD, pady=(t.CARD_PAD, t.SPACE_SM))

        section_title(inner, "Schedule").grid(row=0, column=0, sticky="w", pady=(0, t.SPACE_SM))

        self.star_bonus_switch = ctk.CTkSwitch(
            inner,
            text="Star Bonus",
            font=ctk.CTkFont(size=t.FONT_BODY),
            onvalue=True,
            offvalue=False,
            command=self._on_star_bonus_toggle,
        )
        self.star_bonus_switch.grid(row=1, column=0, sticky="w")

        self.timer_frame = ctk.CTkFrame(card_schedule, fg_color="transparent")
        self.timer_frame.grid(row=1, column=0, sticky="ew", padx=t.CARD_PAD, pady=(0, t.CARD_PAD))
        self.timer_frame.grid_columnconfigure(2, weight=1)

        self.label_duration = ctk.CTkLabel(
            self.timer_frame,
            text="Duration",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t.COLOR_TEXT_MUTED,
        )
        self.label_duration.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, t.SPACE_SM))

        vcmd = (self.register(self._validate_duration), "%P")
        self.entry_minutes = ctk.CTkEntry(
            self.timer_frame,
            width=70,
            height=t.H_MD,
            font=ctk.CTkFont(size=t.FONT_BUTTON_LG),
            placeholder_text="15",
            validate="key",
            validatecommand=vcmd,
        )
        self.entry_minutes.insert(0, "15")
        self.entry_minutes.grid(row=1, column=0, sticky="w", padx=(0, t.SPACE_SM), pady=(0, t.SPACE_SM))

        self.label_minutes = ctk.CTkLabel(
            self.timer_frame,
            text="minutes",
            font=ctk.CTkFont(size=t.FONT_BODY),
            text_color=t.COLOR_TEXT_MUTED,
        )
        self.label_minutes.grid(row=1, column=1, sticky="w", pady=(0, t.SPACE_SM))

        preset_row = ctk.CTkFrame(self.timer_frame, fg_color="transparent")
        preset_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 0))
        self.btn_5m = small_chip_button(
            preset_row, text="5m", command=lambda: self._set_minutes("5")
        )
        self.btn_5m.pack(side="left", padx=(0, t.SPACE_SM))
        self.btn_10m = small_chip_button(
            preset_row, text="10m", command=lambda: self._set_minutes("10")
        )
        self.btn_10m.pack(side="left", padx=(0, t.SPACE_SM))
        self.btn_20m = small_chip_button(
            preset_row, text="20m", command=lambda: self._set_minutes("20")
        )
        self.btn_20m.pack(side="left")

    def _build_modes_card(self, left_col: ctk.CTkFrame) -> None:
        card_modes = card(left_col)
        card_modes.grid(row=2, column=0, sticky="ew", pady=(0, t.CARD_GAP))
        card_modes.grid_columnconfigure(0, weight=1)

        opt_row = ctk.CTkFrame(card_modes, fg_color="transparent")
        opt_row.grid(row=0, column=0, sticky="ew", padx=t.CARD_PAD, pady=(t.CARD_PAD, t.CARD_PAD))
        opt_row.grid_columnconfigure(0, weight=1)

        section_title(opt_row, "Modes").grid(row=0, column=0, sticky="w", pady=(0, t.SPACE_SM), columnspan=2)

        self.ranked_attack_switch = ctk.CTkSwitch(
            opt_row,
            text="Ranked attack fill",
            font=ctk.CTkFont(size=t.FONT_BODY),
            onvalue=True,
            offvalue=False,
            **t.RANKED_SWITCH_COLORS,
        )
        self.ranked_attack_switch.grid(row=1, column=0, sticky="w", columnspan=2)

        self.upgrade_walls_switch = ctk.CTkSwitch(
            opt_row,
            text="Upgrade walls",
            font=ctk.CTkFont(size=t.FONT_BODY),
            onvalue=True,
            offvalue=False,
        )
        self.upgrade_walls_switch.grid(row=2, column=0, sticky="w", columnspan=2, pady=(t.SPACE_SM, 0))

        mr_row = ctk.CTkFrame(opt_row, fg_color="transparent")
        mr_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(t.SPACE_MD, 0))
        mr_row.grid_columnconfigure(0, weight=1)

        self.multi_run_switch = ctk.CTkSwitch(
            mr_row,
            text="Multi-run",
            font=ctk.CTkFont(size=t.FONT_BODY),
            onvalue=True,
            offvalue=False,
        )
        self.multi_run_switch.grid(row=0, column=0, sticky="w")

        self.btn_player_list = neutral_button(
            mr_row,
            text="Player list…",
            command=self._open_player_list,
            width=110,
            height=t.H_SM,
        )
        self.btn_player_list.grid(row=0, column=1, sticky="e", padx=(t.SPACE_MD, 0))

    def _build_controls_card(self, left_col: ctk.CTkFrame) -> None:
        card_controls = card(left_col)
        card_controls.grid(row=3, column=0, sticky="ew", pady=(0, t.CARD_GAP))
        card_controls.grid_columnconfigure((0, 1), weight=1)

        self.btn_start = primary_button(
            card_controls,
            text="Start",
            command=self.start_bot,
            height=t.H_LG,
            font=ctk.CTkFont(size=t.FONT_BUTTON_LG, weight="bold"),
            corner_radius=10,
        )
        self.btn_start.grid(row=0, column=0, padx=(t.CARD_PAD, t.SPACE_SM), pady=(t.CARD_PAD, t.SPACE_SM), sticky="ew")

        self.btn_stop = danger_button(
            card_controls,
            text="Stop",
            command=self.stop_bot,
            height=t.H_LG,
            font=ctk.CTkFont(size=t.FONT_BUTTON_LG, weight="bold"),
            corner_radius=10,
            state="disabled",
        )
        self.btn_stop.grid(row=0, column=1, padx=(t.SPACE_SM, t.CARD_PAD), pady=(t.CARD_PAD, t.SPACE_SM), sticky="ew")

        self.btn_open_log = neutral_button(
            card_controls,
            text="Error Log",
            command=self._open_autoloot_log,
            height=t.H_MD,
            corner_radius=10,
        )
        self.btn_open_log.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=t.CARD_PAD,
            pady=(0, t.CARD_PAD),
            sticky="ew",
        )

    def _build_status_bar(self) -> None:
        status_frame = ctk.CTkFrame(
            self, fg_color=t.CARD_FG, height=40, corner_radius=0, border_width=0
        )
        status_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Ready",
            font=ctk.CTkFont(size=t.FONT_BODY),
            text_color=t.COLOR_TEXT_MUTED,
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=t.PAD_OUTER, pady=10)

    # ── License helpers ───────────────────────────────────────────────────────

    _DOT_COLORS = {
        LicenseState.VALID: t.COLOR_SUCCESS,
        LicenseState.VALIDATING: t.COLOR_WARNING,
        LicenseState.RETRYING: t.COLOR_WARNING,
        LicenseState.INVALID: t.COLOR_DANGER,
        LicenseState.EMPTY: t.COLOR_DANGER,
        LicenseState.STALE: t.COLOR_DANGER,
        LicenseState.UNREACHABLE: t.COLOR_DANGER,
    }

    def _active_license_dialog(self) -> Optional[Any]:
        d = getattr(self, "_license_dialog", None)
        if d is not None and d.winfo_exists():
            return d
        return None

    def _open_license_dialog(self) -> None:
        if self._license_dialog is None or not self._license_dialog.winfo_exists():
            self._license_dialog = LicenseKeyDialog(self)
        dlg = self._license_dialog
        dlg.deiconify()
        dlg.lift(self)
        dlg.focus()
        st = self._license_mgr.state
        dlg.sync_activate_buttons(st)
        self._refresh_license_visuals(st)
        self._schedule_trial_balance_probe()
        dlg.after(10, lambda: dlg._place_over_parent(self))

    def _open_autoloot_log(self) -> None:
        path = get_autoloot_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.touch()
        except OSError as exc:
            messagebox.showerror(
                "Log file",
                f"Could not create log file:\n{path}\n\n{exc}",
                parent=self,
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except OSError as exc:
            messagebox.showerror(
                "Log file",
                f"Could not open log:\n{path}\n\n{exc}",
                parent=self,
            )

    def _refresh_license_visuals(self, state: LicenseState) -> None:
        self._paint_license_dots(state)
        dlg = self._active_license_dialog()
        if dlg is not None:
            dlg.sync_status_display(self._license_status_caption(state))
        self._update_main_expiry_strip()

    def _paint_license_dots(self, state: LicenseState) -> None:
        color = self._DOT_COLORS.get(state, t.COLOR_DANGER)
        self._main_lic_dot.set_color(color)
        dlg = self._active_license_dialog()
        if dlg is not None:
            dlg.paint_dot_color(color)

    def _license_status_caption(self, state: LicenseState) -> tuple[str, str]:
        if state == LicenseState.VALID:
            return ("Licensed.", t.COLOR_SUCCESS)
        if state == LicenseState.VALIDATING:
            text, color = ("Checking license…", t.COLOR_WARNING_TEXT)
        elif state == LicenseState.RETRYING:
            text, color = ("Reconnecting to license server…", t.COLOR_WARNING_TEXT)
        elif state == LicenseState.STALE:
            text, color = (
                "You edited the key since it was last validated. Click Check Key below to verify.",
                t.COLOR_TEXT_MUTED,
            )
        elif state == LicenseState.EMPTY:
            text, color = (
                "No license yet. Paste your key below, then Check Key.",
                t.COLOR_TEXT_MUTED,
            )
        elif state in (LicenseState.INVALID, LicenseState.UNREACHABLE):
            text, color = (self._license_mgr.user_message, t.COLOR_DANGER)
        else:
            text, color = ("Unknown license status.", t.COLOR_TEXT_MUTED)
        return (text, color)

    def _license_indicator_tooltip_text(self) -> str:
        meaning = (
            "What this is: a quick license status indicator. "
            "Green means the server accepted your key; amber means a check is in progress or retrying "
            "after a connection problem; red means activation is missing, out of date, or failed.\n\n"
            "Right now: "
        )
        state = self._license_mgr.state
        if state == LicenseState.VALID:
            sub = self._license_mgr.license_expiry_subcaption
            base = (
                "active—the key validated successfully. The app also re-checks in the "
                "background on a timer so the bot stays authorized."
            )
            if sub:
                return meaning + base + f"\n\n{sub}."
            return meaning + base
        if state == LicenseState.VALIDATING:
            return meaning + (
                "contacting the license server to verify your key. Wait until the dot turns "
                "green or red."
            )
        if state == LicenseState.RETRYING:
            return meaning + (
                "the server could not be reached; reconnecting automatically on a short interval "
                "before giving up. Check your internet if this lasts."
            )
        if state == LicenseState.STALE:
            return meaning + (
                "the license field was edited since your last successful activation. "
                "Open License key… and click Check Key to verify the current key."
            )
        if state == LicenseState.EMPTY:
            return meaning + (
                "no license key is entered yet. Open License key…, paste your key, and click Check Key."
            )
        if state == LicenseState.INVALID:
            return meaning + self._license_mgr.user_message
        if state == LicenseState.UNREACHABLE:
            return meaning + self._license_mgr.user_message
        return meaning + "unknown state."

    def _schedule_trial_balance_probe(self) -> None:
        if self._license_mgr.state == LicenseState.VALID:
            return
        if self._trial_probe_pending:
            return
        self._trial_probe_pending = True

        def worker() -> None:
            result = fetch_trial_status()
            self.after(0, lambda r=result: self._on_trial_probe_done(r))

        threading.Thread(target=worker, daemon=True).start()

    def _on_trial_probe_done(self, result: TrialResult) -> None:
        self._trial_probe_pending = False
        if self._license_mgr.state == LicenseState.VALID:
            return
        if not result.ok and result.reason in ("network_error", "error"):
            self._update_main_expiry_strip()
            return
        self._trial_remaining_seconds = result.remaining_seconds if result.ok else 0
        self._update_main_expiry_strip()

    def _update_main_expiry_strip(self) -> None:
        lbl = getattr(self, "_main_expiry_strip_label", None)
        if lbl is None:
            return
        try:
            if not lbl.winfo_exists():
                return
        except Exception:
            return

        state = self._license_mgr.state
        if state == LicenseState.VALID:
            sub_raw = self._license_mgr.license_expiry_subcaption
            line = format_license_expires_on_line(sub_raw) if sub_raw else ""
            if line:
                lbl.configure(text=line)
                lbl.grid(row=0, column=3, sticky="w", padx=(10, 0))
            elif lbl.grid_info():
                lbl.grid_remove()
            return

        rs = self._trial_remaining_seconds
        if rs is not None and rs > 0:
            lbl.configure(text=format_trial_expires_in_minutes(rs))
            lbl.grid(row=0, column=3, sticky="w", padx=(10, 0))
        elif lbl.grid_info():
            lbl.grid_remove()

    def _on_license_state_change(self, state: LicenseState, reason: str) -> None:
        self.after(0, lambda s=state, r=reason: self._apply_license_state(s, r))

    def _apply_license_state(self, state: LicenseState, reason: str) -> None:
        if state == LicenseState.VALID:
            self._trial_remaining_seconds = None
        elif reason != "stale":
            self._schedule_trial_balance_probe()

        dlg = self._active_license_dialog()
        if dlg is not None:
            dlg.sync_activate_buttons(state)

        if reason != "stale" or dlg is None:
            self._refresh_license_visuals(state)
        else:
            self._update_main_expiry_strip()

        if state == LicenseState.VALID and self._trial_tick_job is not None:
            self._flush_trial_heartbeat()

        if state in (LicenseState.INVALID, LicenseState.UNREACHABLE):
            if self.bot_thread and self.bot_thread.is_alive():
                reason_msg = self._license_mgr.user_message
                self.stop_bot()
                messagebox.showerror(
                    "License Revoked",
                    f"The bot has been stopped.\n\n{reason_msg}",
                )

    def _setup_taskbar_thumb(self) -> None:
        if not TaskbarThumb or self._taskbar_thumb:
            return
        self.update_idletasks()
        try:
            self._taskbar_thumb = TaskbarThumb(
                on_start=self._on_taskbar_start,
                on_stop=self._on_taskbar_stop,
            )
            if self._taskbar_thumb.setup(self):
                self._taskbar_thumb.update_buttons(running=False)
            else:
                self._taskbar_thumb = None
        except Exception as e:
            logger.warning("Taskbar thumb setup failed: %s", e, exc_info=True)
            self._taskbar_thumb = None

    def _on_taskbar_start(self) -> None:
        if not (self.bot_thread and self.bot_thread.is_alive()):
            self.start_bot()

    def _on_taskbar_stop(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            self.stop_bot()

    def _validate_duration(self, value: str) -> bool:
        if value == "":
            return True
        return len(value) <= 3 and value.isdigit()

    def _on_star_bonus_toggle(self) -> None:
        grey = "gray40"
        if self.star_bonus_switch.get():
            self.entry_minutes.configure(state="disabled", text_color=grey)
            self.label_duration.configure(text_color=grey)
            self.label_minutes.configure(text_color=grey)
            self.btn_5m.configure(state="disabled")
            self.btn_10m.configure(state="disabled")
            self.btn_20m.configure(state="disabled")
        else:
            self.entry_minutes.configure(state="normal", text_color=(t.COLOR_TEXT, t.COLOR_TEXT))
            self.label_duration.configure(text_color=t.COLOR_TEXT_MUTED)
            self.label_minutes.configure(text_color=t.COLOR_TEXT_MUTED)
            self.btn_5m.configure(state="normal")
            self.btn_10m.configure(state="normal")
            self.btn_20m.configure(state="normal")

    def _set_minutes(self, value: str) -> None:
        self.entry_minutes.delete(0, "end")
        self.entry_minutes.insert(0, value)

    def _open_profile_settings(self) -> None:
        ProfileSettingsDialog(self)

    def _open_player_list(self) -> None:
        PlayerListDialog(self)

    def _multi_run_players_for_start(self) -> Optional[List[PlayerEntry]]:
        if not self.multi_run_switch.get():
            return None
        players = load_players()
        if not any(p.enabled and p.name.strip() for p in players):
            return []
        return players

    def _get_method(self) -> int:
        return t.ATTACK_STRATEGIES.get(self.attack_choice.get(), 1)

    def _get_minutes(self) -> int:
        try:
            return int(self.entry_minutes.get() or "0")
        except ValueError:
            return 0

    def start_bot(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            return

        if self._license_mgr.state != LicenseState.VALID:
            if self._license_mgr.state == LicenseState.EMPTY:
                messagebox.showerror(
                    "No license",
                    "Checking trial balance…\n\nEnter a license key (License key…) to skip the trial.",
                )
            result = fetch_trial_status()
            if not result.allowed:
                mins = TRIAL_TOTAL_SECONDS // 60
                messagebox.showerror(
                    "Trial expired",
                    f"Your {mins}-minute free trial has been used up.\n\n"
                    "Check Key with a valid license key or purchase one to keep using the bot.",
                )
                return
            self._trial_remaining_seconds = result.remaining_seconds
            self._update_main_expiry_strip()

        if not check_game_window_aspect_for_start(parent=self):
            return

        method = self._get_method()
        multi_arg = self._multi_run_players_for_start()
        if self.multi_run_switch.get() and not multi_arg:
            messagebox.showerror(
                "Multi-run",
                "Enable at least one player with Run and a non-empty name.\nOpen Player list… to edit.",
            )
            return

        if not self.star_bonus_switch.get():
            mins = self._get_minutes()
            if mins <= 0 or mins > 999:
                messagebox.showerror("Error", "Invalid time duration. Enter 1-999 minutes.")
                return
        if self.ranked_attack_switch.get():
            x = self._get_minutes()
            if not RankedAttackConfirmDialog.ask(self, x):
                return

        if self.star_bonus_switch.get():
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.status_label.configure(text="Star Bonus...", text_color=t.COLOR_TEXT_MUTED)
            if self._taskbar_thumb:
                self._taskbar_thumb.update_buttons(running=True)
            self.bot_thread = threading.Thread(
                target=self._run_star_bonus_thread,
                args=(method, multi_arg),
                daemon=True,
            )
            self.bot_thread.start()
        else:
            mins = self._get_minutes()

            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.status_label.configure(text="Running...", text_color=t.COLOR_TEXT_MUTED)
            if self._taskbar_thumb:
                self._taskbar_thumb.update_buttons(running=True)
            self.bot_thread = threading.Thread(
                target=self._run_bot_thread,
                args=(method, mins, multi_arg),
                daemon=True,
            )
            self.bot_thread.start()

        if self._license_mgr.state != LicenseState.VALID:
            self._begin_trial_heartbeat_scheduler()

    def _run_star_bonus_thread(self, method: Any, multi_run_players: Any) -> None:
        def on_status(msg: str) -> None:
            self.after(0, lambda m=msg: self._update_status(m, warning="not found" in m.lower()))

        try:
            self.bot.start(
                method,
                5,
                star_bonus=True,
                status_callback=on_status,
                multi_run_players=multi_run_players,
                ranked_fill=self.ranked_attack_switch.get(),
                upgrade_walls=self.upgrade_walls_switch.get(),
                earthquake_method=load_profile_settings().earthquake_method,
            )
            error_msg = None
        except Exception as e:
            error_msg = str(e)
        self.after(0, lambda: self._on_bot_finished(error_msg))

    def _run_bot_thread(self, method: Any, mins: int, multi_run_players: Any) -> None:
        def on_status(msg: str) -> None:
            self.after(0, lambda m=msg: self._update_status(m, warning="not found" in m.lower()))

        try:
            self.bot.start(
                method,
                mins,
                status_callback=on_status,
                multi_run_players=multi_run_players,
                ranked_fill=self.ranked_attack_switch.get(),
                upgrade_walls=self.upgrade_walls_switch.get(),
                earthquake_method=load_profile_settings().earthquake_method,
            )
            error_msg = None
        except Exception as e:
            error_msg = str(e)
        self.after(0, lambda: self._on_bot_finished(error_msg))

    def stop_bot(self) -> None:
        self._flush_trial_heartbeat()
        self.bot.stop()
        self.status_label.configure(text="Stopping...", text_color=t.COLOR_TEXT_MUTED)

    def _update_status(self, msg: str, warning: bool = False) -> None:
        color = t.COLOR_DANGER if warning else t.COLOR_TEXT_MUTED
        self.status_label.configure(text=msg, text_color=color)

    def _on_bot_finished(self, error_msg: Optional[str] = None) -> None:
        self._flush_trial_heartbeat()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if self._taskbar_thumb:
            self._taskbar_thumb.update_buttons(running=False)
        if error_msg:
            preview = error_msg[:50] + "..." if len(error_msg) > 50 else error_msg
            self.status_label.configure(text=f"Error: {preview}", text_color=t.COLOR_DANGER)
            messagebox.showerror("Error", error_msg)
        else:
            self.status_label.configure(text="Stopped", text_color=t.COLOR_TEXT_MUTED)
            try:
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass
        if self._license_mgr.state != LicenseState.VALID:
            self._schedule_trial_balance_probe()

    def _begin_trial_heartbeat_scheduler(self) -> None:
        self._trial_session += 1
        self._trial_last_mono = time.monotonic()
        session = self._trial_session
        self._trial_tick_job = self.after(
            TRIAL_HEARTBEAT_INTERVAL_MS, lambda: self._tick_trial(session)
        )

    def _tick_trial(self, session: int) -> None:
        if session != self._trial_session:
            return
        if self._license_mgr.state == LicenseState.VALID:
            self._trial_tick_job = None
            return

        now = time.monotonic()
        elapsed = int(now - self._trial_last_mono)
        self._trial_last_mono = now

        def _do_heartbeat(session_snap: int) -> None:
            result = send_trial_heartbeat(elapsed)
            if session_snap != self._trial_session:
                return
            self.after(0, lambda r=result, s=session_snap: self._apply_trial_result(r, s))

        threading.Thread(target=_do_heartbeat, args=(session,), daemon=True).start()

    def _apply_trial_result(self, result: Any, session: int) -> None:
        if session != self._trial_session:
            return
        if not result.ok or result.remaining_seconds <= 0:
            self._trial_remaining_seconds = 0
            self._trial_tick_job = None
            self._trial_session += 1
            self._update_main_expiry_strip()
            self.stop_bot()
            messagebox.showwarning(
                "Trial expired",
                "Your free trial time has run out. The bot has been stopped.\n\n"
                "Purchase a license key to continue using the bot.",
            )
            return
        self._trial_remaining_seconds = result.remaining_seconds
        self._update_main_expiry_strip()
        self._trial_tick_job = self.after(
            TRIAL_HEARTBEAT_INTERVAL_MS,
            lambda: self._tick_trial(session),
        )

    def _flush_trial_heartbeat(self) -> None:
        if self._trial_tick_job is not None:
            try:
                self.after_cancel(self._trial_tick_job)
            except Exception:
                pass
            self._trial_tick_job = None

        session_snap = self._trial_session
        self._trial_session += 1

        if self._license_mgr.state == LicenseState.VALID:
            return

        now = time.monotonic()
        elapsed = int(now - self._trial_last_mono)
        if elapsed <= 0:
            return

        def _flush(elapsed_: int) -> None:
            send_trial_heartbeat(elapsed_)

        threading.Thread(target=_flush, args=(elapsed,), daemon=True).start()


def _primary_monitor_work_rect(root: ctk.CTk) -> tuple[int, int, int, int]:
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = (
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                )

            r = RECT()
            SPI_GETWORKAREA = 48
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(r), 0
            ):
                vw = max(1, int(r.right) - int(r.left))
                vh = max(1, int(r.bottom) - int(r.top))
                return int(r.left), int(r.top), vw, vh
        except Exception:
            pass
    sw = max(1, root.winfo_screenwidth())
    sh = max(1, root.winfo_screenheight())
    return 0, 0, sw, sh


def _center_main_window(root: ctk.CTk) -> None:
    root.update_idletasks()
    w = root.winfo_reqwidth()
    h = root.winfo_reqheight()
    aw, ah = root.winfo_width(), root.winfo_height()
    if aw > 1 and aw > w:
        w = aw
    if ah > 1 and ah > h:
        h = ah
    w = max(w, 1)
    h = max(h, 1)

    vx, vy, vw, vh = _primary_monitor_work_rect(root)
    x = vx + max(0, (vw - w) // 2)
    y = vy + max(0, (vh - h) // 2)
    x = max(vx, min(x, vx + max(0, vw - w)))
    y = max(vy, min(y, vy + max(0, vh - h)))
    root.geometry(f"+{x}+{y}")


def run_gui() -> None:
    app = AutoLootApp()
    _center_main_window(app)
    app.after(100, lambda a=app: _center_main_window(a))
    app.mainloop()