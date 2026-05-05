import customtkinter as ctk
from tkinter import Label, Toplevel, messagebox
from tkinter import Canvas as TkCanvas
import os
import subprocess
import sys
import threading
import time
import winsound
import platform
import webbrowser
from typing import Any, Callable, Dict, List, Optional
from app.config import check_game_window_aspect_for_start
from app.core.bot import Bot
from app.utils.common import get_autoloot_log_path
from app.utils.logger import setup_logger
from app.utils.player_list_store import PlayerEntry, load_players, save_players
from app.services.license import (
    LicenseManager,
    LicenseState,
    clear_saved_key,
    load_saved_key,
)
from app.services.trial import (
    TRIAL_HEARTBEAT_INTERVAL_MS,
    TRIAL_TOTAL_SECONDS,
    TrialResult,
    fetch_trial_status,
    send_trial_heartbeat,
)

logger = setup_logger("GUI")


def _format_license_expires_on_line(sub: str) -> str:
    """Normalize subscription/lifetime line to start with 'Expires on:'."""
    s = sub.strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("expires on:"):
        rest = s.split(":", 1)[1].strip()
        return f"Expires on: {rest}"
    return f"Expires on: {s}"


def _format_trial_expires_in_minutes(remaining_seconds: int) -> str:
    mins = max(1, (int(remaining_seconds) + 59) // 60)
    unit = "minute" if mins == 1 else "minutes"
    return f"Expires in: {mins} {unit}"


if platform.system() == "Windows":
    try:
        from app.services.taskbar_thumb import TaskbarThumb
    except ImportError:
        TaskbarThumb = None
else:
    TaskbarThumb = None

ATTACK_MAP = {"Sneaky Goblins": 1, "Super Minions": 2, "Valkyries": 3}

# Design tokens
PAD = 16
CARD_PAD = 14
CORNER = 12
CARD_BG = ("#2b2b2b", "#1a1a1a")
BORDER = ("#3d3d3d", "#2d2d2d")
ACCENT = "#0ea5e9"
ACCENT_HOVER = "#0284c7"
DANGER = "#ef4444"
DANGER_HOVER = "#dc2626"
TEXT_MUTED = "#94a3b8"
RUN_GREEN = "#22c55e"
RUN_GREEN_HOVER = "#16a34a"

# License popup stays this size so status updates don't resize the window; long text scrolls.
LICENSE_POPUP_WIDTH = 480
LICENSE_POPUP_HEIGHT = 520
_LICENSE_STATUS_BODY_W = 400
_LICENSE_STATUS_BODY_H = 120
# Stripe Payment Link / hosted checkout for one-time lifetime license.
STRIPE_LIFETIME_CHECKOUT_URL = "https://buy.stripe.com/14AbJ12fBfOx6jpaOB2Ry00"
# FastAPI redirects to Stripe Checkout (secret + custom_fields stay on the server).
MONTH_EXTEND_CHECKOUT_REDIRECT = "https://clashautoloot.duckdns.org/v1/checkout/month-extend"

UNPAIR_CONFIRM_DIALOG_W = 440
UNPAIR_CONFIRM_DIALOG_H = 420


_UNPAIR_USER_ERRORS: dict[str, str] = {
    "empty": "No license key was entered.",
    "invalid_format": "That license key is not formatted correctly.",
    "not_found": "That license key was not found.",
    "revoked": "This license key has been revoked.",
    "machine_mismatch": "This PC was not paired with this key, so nothing was changed on the server.",
    "not_bound": "No machine was paired yet; your local saved key will still be removed.",
    "network_unreachable": "Could not reach the license server. Check your internet and try again.",
    "failed": "The server declined the request. Try again or contact support.",
}


class _HoverTooltip:
    """Small themed tooltip after a hover delay; allows moving onto the balloon to read."""

    _SHOW_DELAY_MS = 420
    _HIDE_DELAY_MS = 160

    def __init__(self, widget: Any, get_text: Callable[[], str]) -> None:
        self.widget = widget
        self.get_text = get_text
        self._tip: Optional[Toplevel] = None
        self._show_job: Optional[Any] = None
        self._hide_job: Optional[Any] = None

        widget.bind("<Enter>", self._on_widget_enter, add="+")
        widget.bind("<Leave>", self._on_widget_leave, add="+")

    def _cancel_show(self) -> None:
        if self._show_job is not None:
            self.widget.after_cancel(self._show_job)
            self._show_job = None

    def _cancel_hide(self) -> None:
        if self._hide_job is not None:
            self.widget.after_cancel(self._hide_job)
            self._hide_job = None

    def destroy_tip(self) -> None:
        self._cancel_show()
        self._cancel_hide()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _on_widget_enter(self, _event=None) -> None:
        self._cancel_hide()
        self._cancel_show()
        self._show_job = self.widget.after(self._SHOW_DELAY_MS, self._show_tip)

    def _on_widget_leave(self, _event=None) -> None:
        self._cancel_show()
        self._hide_job = self.widget.after(self._HIDE_DELAY_MS, self.destroy_tip)

    def _show_tip(self) -> None:
        self._show_job = None
        text = self.get_text().strip()
        if not text:
            return
        self.destroy_tip()
        bg = "#0f172a"
        fg = "#e2e8f0"
        border = "#334155"

        root = self.widget.winfo_toplevel()
        tip = Toplevel(root)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        label = Label(
            tip,
            text=text,
            justify="left",
            wraplength=300,
            background=bg,
            foreground=fg,
            highlightthickness=1,
            highlightbackground=border,
            padx=10,
            pady=8,
            font=("Segoe UI", 10),
        )
        label.pack()

        label.bind("<Enter>", lambda _e: self._cancel_hide(), add="+")
        label.bind("<Leave>", self._on_widget_leave, add="+")

        tip.update_idletasks()
        tw_w = tip.winfo_reqwidth()
        tw_h = tip.winfo_reqheight()

        wx = self.widget.winfo_rootx()
        wy = self.widget.winfo_rooty()
        ww = self.widget.winfo_width()
        wh = self.widget.winfo_height()
        x = wx + max(0, (ww - tw_w) // 2)
        y = wy + wh + 6
        sw = tip.winfo_screenwidth()
        sh = tip.winfo_screenheight()
        x = max(8, min(x, sw - tw_w - 8))
        y = max(8, min(y, sh - tw_h - 8))
        tip.geometry(f"+{x}+{y}")
        self._tip = tip


class PlayerListDialog(ctk.CTkToplevel):
    """Edit multi-run player order, names, and Run/Skip per row."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Player list")
        self.geometry("560x460")
        self.transient(master)
        self.grab_set()
        self._rows: List[Dict[str, Any]] = []

        hint = ctk.CTkLabel(
            self,
            text="Order is rotation order (↑↓). Run (green) = farm this account; Skip (red) = ignore.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            wraplength=520,
            justify="left",
        )
        hint.pack(anchor="w", padx=PAD, pady=(PAD, 6))

        self.scroll = ctk.CTkScrollableFrame(self, width=520, height=280)
        self.scroll.pack(fill="both", expand=True, padx=PAD, pady=(0, 8))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=PAD, pady=(0, PAD))
        ctk.CTkButton(bottom, text="Add player", width=100, command=self._add_empty_row).pack(
            side="left"
        )
        ctk.CTkButton(
            bottom,
            text="Done",
            width=100,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self._on_done,
        ).pack(side="right")

        for p in load_players():
            self._add_row(p.name, p.enabled)
        if not self._rows:
            self._add_empty_row()

        self.protocol("WM_DELETE_WINDOW", self._on_done)

    def _apply_mode_colors(self, mode: ctk.CTkSegmentedButton) -> None:
        if mode.get() == "Run":
            mode.configure(selected_color=RUN_GREEN, selected_hover_color=RUN_GREEN_HOVER)
        else:
            mode.configure(selected_color=DANGER, selected_hover_color=DANGER_HOVER)

    def _add_empty_row(self) -> None:
        self._add_row("", True)

    def _reflow_rows(self) -> None:
        for r in self._rows:
            r["frame"].pack_forget()
        for r in self._rows:
            r["frame"].pack(fill="x", pady=4)

    def _move_row(self, row_f: ctk.CTkFrame, delta: int) -> None:
        idx = next((i for i, r in enumerate(self._rows) if r["frame"] is row_f), None)
        if idx is None:
            return
        j = idx + delta
        if j < 0 or j >= len(self._rows):
            return
        self._rows[idx], self._rows[j] = self._rows[j], self._rows[idx]
        self._reflow_rows()
        self._save()

    def _add_row(self, name: str, enabled: bool) -> None:
        row_f = ctk.CTkFrame(self.scroll, fg_color="transparent")
        row_f.pack(fill="x", pady=4)

        entry = ctk.CTkEntry(row_f, width=210, placeholder_text="Username (match in-game)")
        if name:
            entry.insert(0, name)
        entry.pack(side="left", padx=(0, 6))
        entry.bind("<FocusOut>", lambda _e: self._save())
        entry.bind("<Return>", lambda _e: self._save())

        mode = ctk.CTkSegmentedButton(row_f, values=["Run", "Skip"], width=118, height=30)
        mode.set("Run" if enabled else "Skip")

        def on_change(_v: str) -> None:
            self._apply_mode_colors(mode)
            self._save()

        mode.configure(command=on_change)
        self._apply_mode_colors(mode)
        mode.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            row_f,
            text="↑",
            width=30,
            height=30,
            font=ctk.CTkFont(size=14),
            command=lambda rf=row_f: self._move_row(rf, -1),
        ).pack(side="left", padx=(0, 2))
        ctk.CTkButton(
            row_f,
            text="↓",
            width=30,
            height=30,
            font=ctk.CTkFont(size=14),
            command=lambda rf=row_f: self._move_row(rf, 1),
        ).pack(side="left", padx=(0, 6))

        def remove() -> None:
            self._rows = [r for r in self._rows if r["frame"] is not row_f]
            row_f.destroy()
            self._save()

        ctk.CTkButton(
            row_f,
            text="Remove",
            width=72,
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            command=remove,
        ).pack(side="left")

        self._rows.append({"frame": row_f, "entry": entry, "mode": mode})

    def _collect_players(self) -> List[PlayerEntry]:
        players: List[PlayerEntry] = []
        for r in self._rows:
            nm = r["entry"].get().strip()
            if not nm:
                continue
            en = r["mode"].get() == "Run"
            players.append(PlayerEntry(name=nm, enabled=en))
        return players

    def _save(self) -> None:
        save_players(self._collect_players())

    def _on_done(self) -> None:
        self._save()
        self.destroy()


class RankedAttackConfirmDialog(ctk.CTkToplevel):
    """Modal confirm for ranked attack fill; Yes stays disabled for 5 seconds."""

    def __init__(self, master, minutes: int):
        super().__init__(master)
        self._parent = master
        self._result = False
        self._after_id: Any = None
        self.title("Ranked attack fill")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        msg = (
            f"The bot will use up your ranked attacks up to {minutes} minutes, "
            "are you sure you want to continue?"
        )
        ctk.CTkLabel(
            self,
            text=msg,
            font=ctk.CTkFont(size=13),
            text_color=("gray10", "gray90"),
            wraplength=400,
            justify="left",
        ).pack(anchor="w", padx=PAD, pady=(PAD, 8))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=PAD, pady=(0, PAD))

        self._remaining = 5
        self._btn_yes = ctk.CTkButton(
            row,
            text="Yes (5)",
            width=100,
            height=32,
            state="disabled",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            command=self._on_yes,
        )
        self._btn_yes.pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            row,
            text="No",
            width=100,
            height=32,
            font=ctk.CTkFont(size=13),
            fg_color=("gray50", "gray40"),
            hover_color=("gray40", "gray30"),
            command=self._on_no,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_no)
        self._after_id = self.after(0, self._tick_countdown)
        self.after(10, self._place_over_parent)

    def _place_over_parent(self) -> None:
        """Center the dialog on the main bot window (not the top-left of the screen)."""
        if not self.winfo_exists():
            return
        parent = self._parent
        self.update_idletasks()
        parent.update_idletasks()
        w = self.winfo_width() or self.winfo_reqwidth()
        h = self.winfo_height() or self.winfo_reqheight()
        pw = max(parent.winfo_width(), parent.winfo_reqwidth())
        ph = max(parent.winfo_height(), parent.winfo_reqheight())
        x = int(parent.winfo_rootx() + (pw - w) // 2)
        y = int(parent.winfo_rooty() + (ph - h) // 2)
        self.geometry(f"+{x}+{y}")
        self.lift(parent)
        self.focus()

    def _cancel_after(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _tick_countdown(self) -> None:
        self._after_id = None
        if not self.winfo_exists():
            return
        if self._remaining > 0:
            self._btn_yes.configure(text=f"Yes ({self._remaining})", state="disabled")
            self._remaining -= 1
            self._after_id = self.after(1000, self._tick_countdown)
        else:
            self._btn_yes.configure(text="Yes", state="normal")

    def _on_yes(self) -> None:
        self._result = True
        self._cancel_after()
        self.grab_release()
        self.destroy()

    def _on_no(self) -> None:
        self._result = False
        self._cancel_after()
        if self.winfo_exists():
            self.grab_release()
            self.destroy()

    @staticmethod
    def ask(master, minutes: int) -> bool:
        d = RankedAttackConfirmDialog(master, minutes)
        master.wait_window(d)
        return d._result


class UnpairConfirmDialog(ctk.CTkToplevel):
    """Confirm unpair + show key copy; runs server request on a worker thread."""

    def __init__(self, license_dialog: Any, app: Any, license_key_display: str) -> None:
        super().__init__(license_dialog)
        self._license_dialog = license_dialog
        self._app = app
        self._snap = license_key_display.strip().upper()

        self.title("Unpair this PC")
        self.resizable(False, False)
        self.transient(license_dialog)
        self.grab_set()
        self.configure(fg_color=("#1e1e1e", "#0f0f0f"))

        pad = PAD
        ctk.CTkLabel(
            self,
            text=(
                "This will permanently remove THIS computer from your license binding on "
                "our server, and delete the license file saved under your Windows user folder.\n\n"
                "• You will need Check Key again later to reuse the same key.\n\n"
                "Copy your license key below if you need it for another PC or reinstall."
            ),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            wraplength=UNPAIR_CONFIRM_DIALOG_W - pad * 2,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=pad, pady=(pad, 12))

        ctk.CTkLabel(
            self,
            text="Your license key",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", padx=pad)

        key_row = ctk.CTkFrame(self, fg_color="transparent")
        key_row.pack(fill="x", padx=pad, pady=(4, pad))
        key_row.grid_columnconfigure(0, weight=1)

        self._key_disp = ctk.CTkEntry(
            key_row,
            height=38,
            font=ctk.CTkFont(size=14, family="Courier New"),
        )
        self._key_disp.insert(0, self._snap)
        self._key_disp.configure(state="disabled")
        self._key_disp.grid(row=0, column=0, sticky="ew")

        copy_btn = ctk.CTkButton(
            key_row,
            text="Copy",
            width=80,
            height=38,
            command=self._copy_key,
        )
        copy_btn.grid(row=0, column=1, padx=(8, 0))

        row_btns = ctk.CTkFrame(self, fg_color="transparent")
        row_btns.pack(fill="x", padx=pad, pady=(0, pad))

        ctk.CTkButton(
            row_btns,
            text="Cancel",
            width=100,
            height=32,
            fg_color=("gray50", "gray40"),
            hover_color=("gray40", "gray35"),
            command=self._on_cancel,
        ).pack(side="left")

        self._btn_unpair = ctk.CTkButton(
            row_btns,
            text="Unpair this PC",
            width=150,
            height=32,
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            command=self._on_confirm_unpair,
        )
        self._btn_unpair.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        W, H = UNPAIR_CONFIRM_DIALOG_W, UNPAIR_CONFIRM_DIALOG_H
        self.geometry(f"{W}x{H}")
        self.after(12, lambda: self._center_on(license_dialog))

    def _center_on(self, parent: Any) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        parent.update_idletasks()
        W, H = UNPAIR_CONFIRM_DIALOG_W, UNPAIR_CONFIRM_DIALOG_H
        pw = max(parent.winfo_width(), parent.winfo_reqwidth())
        ph = max(parent.winfo_height(), parent.winfo_reqheight())
        x = int(parent.winfo_rootx() + (pw - W) // 2)
        y = int(parent.winfo_rooty() + (ph - H) // 2)
        self.geometry(f"{W}x{H}+{x}+{y}")
        self.lift(parent)

    def _copy_key(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._snap)
        self.update()

    def _on_cancel(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _on_confirm_unpair(self) -> None:
        self._btn_unpair.configure(state="disabled", text="Working…")

        def worker() -> None:
            ok, reason_code = self._app._license_mgr.try_unpair(self._snap)

            def ui_done() -> None:
                if not self.winfo_exists():
                    return
                self._btn_unpair.configure(state="normal", text="Unpair this PC")
                if ok:
                    clear_saved_key()
                    self._license_dialog._entry.delete(0, "end")
                    self._app._license_mgr.recheck(new_key="")
                    self._on_cancel()
                    messagebox.showinfo(
                        "Unpaired",
                        "This PC was unpaired from the license and your saved key file was removed.",
                        parent=self._app,
                    )
                else:
                    msg = _UNPAIR_USER_ERRORS.get(reason_code, reason_code.replace("_", " ").title())
                    messagebox.showerror("Could not unpair", msg, parent=self._app)

            self._app.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()


class LicenseKeyDialog(ctk.CTkToplevel):
    """Minimal license-entry window (hidden via withdraw until opened from main UI)."""

    _LICENSE_STATUS_DEBOUNCE_MS = 200

    def __init__(self, app: Any):
        super().__init__(app)
        self._app = app
        self.title("License Key")
        self.resizable(False, False)
        self.transient(app)
        self.configure(fg_color=("#1e1e1e", "#0f0f0f"))

        card = app._card(self)
        card.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=(
                "Edit your license key below. Nothing is saved or sent until you "
                "press Check Key — then the saved key file updates only if the "
                "server accepts it."
            ),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            wraplength=400,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=CARD_PAD, pady=(CARD_PAD, 6))

        self._status_text = ctk.CTkTextbox(
            card,
            width=_LICENSE_STATUS_BODY_W,
            height=_LICENSE_STATUS_BODY_H,
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
            fg_color=("gray22", "#1c1c22"),
            border_width=1,
            border_color=BORDER,
            corner_radius=CORNER,
            activate_scrollbars=True,
            takefocus=False,
        )
        self._status_text.grid(row=1, column=0, sticky="ew", padx=CARD_PAD, pady=(0, 8))
        self._status_text.insert("1.0", "")
        self._status_text.configure(state="disabled")

        lic_row = ctk.CTkFrame(card, fg_color="transparent")
        lic_row.grid(row=2, column=0, sticky="ew", padx=CARD_PAD, pady=(0, 4))
        lic_row.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(
            lic_row,
            placeholder_text="CLASH-XXXX-XXXX-XXXX-XXXX",
            show="*",
            height=34,
            font=ctk.CTkFont(size=13, family="Courier New"),
        )
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._entry.bind("<KeyRelease>", self._on_key_typed)

        self._show_var = False
        ctk.CTkButton(
            lic_row,
            text="👁",
            width=34,
            height=34,
            fg_color=("gray30", "gray25"),
            hover_color=("gray40", "gray35"),
            command=self._toggle_visibility,
        ).grid(row=0, column=1, padx=(0, 6))

        self._lic_canvas = TkCanvas(
            lic_row, width=14, height=14, bg="#1a1a1a", highlightthickness=0
        )
        self._lic_canvas.grid(row=0, column=2, padx=(0, 6))
        self._lic_dot = self._lic_canvas.create_oval(2, 2, 12, 12, fill="#ef4444", outline="")

        _HoverTooltip(self._lic_canvas, app._license_indicator_tooltip_text)

        self._btn_activate = ctk.CTkButton(
            lic_row,
            text="Check Key",
            width=108,
            height=34,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self._on_check_key_clicked,
        )
        self._btn_activate.grid(row=0, column=3)

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=CARD_PAD, pady=(4, CARD_PAD))
        left_btns = ctk.CTkFrame(footer, fg_color="transparent")
        left_btns.pack(side="left")
        self._btn_monthly_extend = ctk.CTkButton(
            left_btns,
            text="Buy / extend subscription",
            width=174,
            height=30,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self._open_monthly_extend_checkout,
        )
        self._btn_monthly_extend.pack(side="left", padx=(0, 8))
        _HoverTooltip(
            self._btn_monthly_extend,
            lambda: "Opens checkout for monthly access ($12 per month). Quantity = months. Paste your key "
            "there to extend, or leave blank for a new key.",
        )
        self._btn_lifetime = ctk.CTkButton(
            left_btns,
            text="Buy lifetime",
            width=118,
            height=30,
            font=ctk.CTkFont(size=13),
            fg_color=("gray35", "gray28"),
            hover_color=("gray45", "gray38"),
            command=self._open_lifetime_checkout,
        )
        self._btn_lifetime.pack(side="left", padx=(0, 8))
        _HoverTooltip(
            self._btn_lifetime,
            lambda: "Opens Stripe Checkout for a one-time lifetime license.",
        )
        ctk.CTkButton(
            left_btns,
            text="Unpair…",
            width=100,
            height=30,
            font=ctk.CTkFont(size=13),
            fg_color=("gray42", "gray32"),
            hover_color=("gray50", "gray40"),
            command=self._open_unpair_confirm,
        ).pack(side="left", padx=(10, 0))
        ctk.CTkButton(
            footer,
            text="Close",
            width=100,
            height=30,
            fg_color=("gray50", "gray40"),
            hover_color=("gray40", "gray35"),
            command=self._hide,
        ).pack(side="right")

        saved = load_saved_key()
        if saved:
            self._entry.insert(0, saved)

        self.geometry(f"{LICENSE_POPUP_WIDTH}x{LICENSE_POPUP_HEIGHT}")
        self.minsize(LICENSE_POPUP_WIDTH, LICENSE_POPUP_HEIGHT)
        self.maxsize(LICENSE_POPUP_WIDTH, LICENSE_POPUP_HEIGHT)

        self.protocol("WM_DELETE_WINDOW", self._hide)
        self.after(10, lambda: self._place_over_parent(app))

        self._license_status_refresh_job: Optional[str] = None

    def _open_lifetime_checkout(self) -> None:
        url = (STRIPE_LIFETIME_CHECKOUT_URL or "").strip()
        if not url:
            messagebox.showinfo(
                "Lifetime license",
                "The lifetime checkout URL is not set in this build yet.\n\n"
                "Contact support to purchase.",
                parent=self,
            )
            return
        webbrowser.open(url)

    def _open_monthly_extend_checkout(self) -> None:
        url = (MONTH_EXTEND_CHECKOUT_REDIRECT or "").strip()
        if not url:
            messagebox.showinfo(
                "Monthly access",
                "The monthly checkout URL is not set in this build yet.\n\n"
                "Try Buy lifetime, or contact support.",
                parent=self,
            )
            return
        webbrowser.open(url)

    def _open_unpair_confirm(self) -> None:
        key = self._entry.get().strip()
        if not key:
            messagebox.showerror(
                "Unpair",
                "Enter your license key in the field above first.",
                parent=self,
            )
            return
        UnpairConfirmDialog(self, self._app, key)

    def _place_over_parent(self, parent: Any) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        parent.update_idletasks()
        W, H = LICENSE_POPUP_WIDTH, LICENSE_POPUP_HEIGHT
        pw = max(parent.winfo_width(), parent.winfo_reqwidth())
        ph = max(parent.winfo_height(), parent.winfo_reqheight())
        x = int(parent.winfo_rootx() + (pw - W) // 2)
        y = int(parent.winfo_rooty() + (ph - H) // 2)
        self.geometry(f"{W}x{H}+{x}+{y}")
        self.lift(parent)

    def _hide(self) -> None:
        self._cancel_pending_license_status_refresh()
        mgr = self._app._license_mgr
        saved = load_saved_key().strip().upper()
        typed = self._entry.get().strip().upper()
        need_recheck = mgr.state == LicenseState.STALE or typed != saved

        self._entry.delete(0, "end")
        if saved:
            self._entry.insert(0, saved)

        if need_recheck:
            mgr.recheck(new_key=saved)
        self.withdraw()

    def _toggle_visibility(self) -> None:
        self._show_var = not self._show_var
        self._entry.configure(show="" if self._show_var else "*")

    def _on_key_typed(self, _event=None) -> None:
        self._app._license_mgr.mark_stale()
        self._btn_activate.configure(text="Check Key")
        app = self._app
        app._paint_license_dots(app._license_mgr.state)
        self._cancel_pending_license_status_refresh()
        self._license_status_refresh_job = app.after(
            self._LICENSE_STATUS_DEBOUNCE_MS,
            self._debounced_license_dialog_status_refresh,
        )

    def _debounced_license_dialog_status_refresh(self) -> None:
        self._license_status_refresh_job = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._app._refresh_license_visuals(self._app._license_mgr.state)

    def _cancel_pending_license_status_refresh(self) -> None:
        jid = self._license_status_refresh_job
        if jid is None:
            return
        try:
            self._app.after_cancel(jid)
        except Exception:
            pass
        self._license_status_refresh_job = None

    def _on_check_key_clicked(self) -> None:
        self._cancel_pending_license_status_refresh()
        key = self._entry.get().strip()
        self._btn_activate.configure(state="disabled")
        self._app._refresh_license_visuals(LicenseState.VALIDATING)
        self._app._license_mgr.recheck(new_key=key)

    def sync_activate_buttons(self, state: LicenseState) -> None:
        self._btn_activate.configure(state="normal", text="Check Key")
        if state == LicenseState.VALIDATING or state == LicenseState.RETRYING:
            self._btn_activate.configure(state="disabled")

    def paint_dot_color(self, color: str) -> None:
        if self.winfo_exists():
            self._lic_canvas.itemconfig(self._lic_dot, fill=color)

    def sync_status_display(self, caption: tuple[str, str]) -> None:
        if not self.winfo_exists():
            return
        text, tint = caption
        tb = self._status_text
        tb.configure(state="normal", text_color=tint)
        tb.delete("1.0", "end")
        tb.insert("1.0", text.rstrip() or " ")
        tb.configure(state="disabled")
        tb.see("1.0")


class AutoLootApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Clash AutoLoot Bot")
        self.resizable(False, False)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.bot = Bot()
        self.bot_thread = None
        self._upgrade_walls_toggle_times: List[float] = []
        self._upgrade_walls_debug_visible = False
        self._taskbar_thumb = None
        self._license_dialog: Any = None

        # Trial runtime tracking
        self._trial_remaining_seconds: Optional[int] = None
        self._trial_last_mono: float = 0.0
        self._trial_tick_job: Optional[str] = None
        self._trial_session: int = 0  # incremented on each start; stale callbacks skip
        self._trial_probe_pending: bool = False

        # License manager — must be created before _init_ui so the main license dot can refresh after start
        from app import __version__
        self._license_mgr = LicenseManager(bot_version=__version__)
        self._license_mgr.set_on_state_change(self._on_license_state_change)

        self._init_ui()

        # Load saved key and kick off first validation in background
        saved_key = load_saved_key()
        self._license_mgr.start(saved_key)
        self._refresh_license_visuals(self._license_mgr.state)
        self.after(1000, self._schedule_trial_balance_probe)

        if TaskbarThumb:
            self.after(500, self._setup_taskbar_thumb)

    def _card(self, parent, **kwargs):
        """Create a card-style frame."""
        return ctk.CTkFrame(
            parent,
            fg_color=CARD_BG,
            corner_radius=CORNER,
            border_width=1,
            border_color=BORDER,
            **kwargs,
        )

    def _init_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.configure(fg_color=("#1e1e1e", "#0f0f0f"))

        # Main content container
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew", padx=PAD, pady=(PAD, 0))
        main.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkLabel(
            main,
            text="Clash AutoLoot",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=("gray90", "gray90"),
        )
        header.grid(row=0, column=0, sticky="w", pady=(0, PAD))

        # ── License strip (compact: dot + popup; expiry line lives on main window only)
        card_license = self._card(main)
        card_license.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        lic_strip = ctk.CTkFrame(card_license, fg_color="transparent")
        lic_strip.grid(row=0, column=0, sticky="ew", padx=CARD_PAD, pady=CARD_PAD)
        lic_strip.grid_columnconfigure(1, weight=1)

        self._main_lic_indicator = TkCanvas(
            lic_strip, width=14, height=14, bg="#1a1a1a", highlightthickness=0
        )
        self._main_lic_indicator.grid(row=0, column=0, padx=(0, 12))
        self._main_lic_dot = self._main_lic_indicator.create_oval(
            2, 2, 12, 12, fill="#ef4444", outline=""
        )
        _HoverTooltip(self._main_lic_indicator, self._license_indicator_tooltip_text)

        self.btn_license = ctk.CTkButton(
            lic_strip,
            text="License key…",
            width=118,
            height=30,
            font=ctk.CTkFont(size=13),
            fg_color=("gray50", "gray40"),
            hover_color=("gray40", "gray35"),
            command=self._open_license_dialog,
        )
        self.btn_license.grid(row=0, column=2, sticky="e")

        self._main_expiry_strip_label = ctk.CTkLabel(
            lic_strip,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        )

        # ── Card: Attack Method ───────────────────────────────────────────────
        card_attack = self._card(main)
        card_attack.grid(row=2, column=0, sticky="ew", pady=(0, 8))  # row 2 = attack
        card_attack.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_attack,
            text="Attack Method",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w", padx=CARD_PAD, pady=(CARD_PAD, 6))

        self.attack_choice = ctk.CTkSegmentedButton(
            card_attack,
            values=["Valkyries", "Sneaky Goblins", "Super Minions"],
            command=lambda _: None,
        )
        self.attack_choice.set("Valkyries")
        self.attack_choice.grid(row=1, column=0, sticky="ew", padx=CARD_PAD, pady=(0, CARD_PAD))

        # Card: Options + Timer
        card_options = self._card(main)
        card_options.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        card_options.grid_columnconfigure(0, weight=1)

        # Options (switches stacked)
        opt_row = ctk.CTkFrame(card_options, fg_color="transparent")
        opt_row.grid(row=0, column=0, sticky="ew", padx=CARD_PAD, pady=(CARD_PAD, 6))
        opt_row.grid_columnconfigure(0, weight=1)

        self.star_bonus_switch = ctk.CTkSwitch(
            opt_row,
            text="Star Bonus",
            font=ctk.CTkFont(size=13),
            onvalue=True,
            offvalue=False,
            command=self._on_star_bonus_toggle,
        )
        self.star_bonus_switch.grid(row=0, column=0, sticky="w")

        self.ranked_attack_switch = ctk.CTkSwitch(
            opt_row,
            text="Ranked attack fill",
            font=ctk.CTkFont(size=13),
            onvalue=True,
            offvalue=False,
            text_color=DANGER,
            fg_color=("#3f3f46", "#27272a"),
            progress_color=DANGER,
            button_color=("#f87171", "#ef4444"),
            button_hover_color=DANGER_HOVER,
        )
        self.ranked_attack_switch.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.upgrade_walls_switch = ctk.CTkSwitch(
            opt_row,
            text="Upgrade walls",
            font=ctk.CTkFont(size=13),
            onvalue=True,
            offvalue=False,
            command=self._on_upgrade_walls_toggle,
        )
        self.upgrade_walls_switch.grid(row=2, column=0, sticky="w", pady=(8, 0))

        self.btn_debug_upgrade_walls = ctk.CTkButton(
            opt_row,
            text="Debug: upgrade walls now",
            font=ctk.CTkFont(size=11),
            height=28,
            fg_color=("gray40", "gray35"),
            hover_color=("gray35", "gray30"),
            command=self._debug_upgrade_walls_click,
        )

        # Timer section (greyed out when Star Bonus is on)
        self.timer_frame = ctk.CTkFrame(card_options, fg_color="transparent")
        self.timer_frame.grid(row=1, column=0, sticky="ew", padx=CARD_PAD, pady=(12, 0))
        self.timer_frame.grid_columnconfigure(1, weight=1)

        self.label_duration = ctk.CTkLabel(
            self.timer_frame,
            text="Duration",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self.label_duration.grid(row=0, column=0, sticky="w", pady=(0, 6))

        vcmd = (self.register(self._validate_duration), "%P")
        self.entry_minutes = ctk.CTkEntry(
            self.timer_frame,
            width=70,
            height=36,
            font=ctk.CTkFont(size=14),
            placeholder_text="15",
            validate="key",
            validatecommand=vcmd,
        )
        self.entry_minutes.insert(0, "15")
        self.entry_minutes.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 8))

        self.label_minutes = ctk.CTkLabel(
            self.timer_frame, text="minutes", font=ctk.CTkFont(size=13), text_color=TEXT_MUTED
        )
        self.label_minutes.grid(row=1, column=1, sticky="w", pady=(0, 8))

        # Presets
        preset_row = ctk.CTkFrame(self.timer_frame, fg_color="transparent")
        preset_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, CARD_PAD))
        self.btn_5m = ctk.CTkButton(preset_row, text="5m", width=45, height=32, command=lambda: self._set_minutes("5"))
        self.btn_5m.pack(side="left", padx=(0, 6))
        self.btn_10m = ctk.CTkButton(preset_row, text="10m", width=45, height=32, command=lambda: self._set_minutes("10"))
        self.btn_10m.pack(side="left", padx=(0, 6))
        self.btn_20m = ctk.CTkButton(preset_row, text="20m", width=45, height=32, command=lambda: self._set_minutes("20"))
        self.btn_20m.pack(side="left")

        # Multi-run
        mr_row = ctk.CTkFrame(card_options, fg_color="transparent")
        mr_row.grid(row=2, column=0, sticky="ew", padx=CARD_PAD, pady=(4, CARD_PAD))
        mr_row.grid_columnconfigure(0, weight=1)

        self.multi_run_switch = ctk.CTkSwitch(
            mr_row,
            text="Multi-run",
            font=ctk.CTkFont(size=13),
            onvalue=True,
            offvalue=False,
        )
        self.multi_run_switch.grid(row=0, column=0, sticky="w")

        self.btn_player_list = ctk.CTkButton(
            mr_row,
            text="Player list…",
            width=110,
            height=30,
            command=self._open_player_list,
        )
        self.btn_player_list.grid(row=0, column=1, sticky="e", padx=(12, 0))

        # Card: Controls
        card_controls = self._card(main)
        card_controls.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        card_controls.grid_columnconfigure((0, 1), weight=1)

        self.btn_start = ctk.CTkButton(
            card_controls,
            text="Start",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            corner_radius=10,
            command=self.start_bot,
        )
        self.btn_start.grid(row=0, column=0, padx=(CARD_PAD, 6), pady=(CARD_PAD, 6), sticky="ew")

        self.btn_stop = ctk.CTkButton(
            card_controls,
            text="Stop",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            corner_radius=10,
            state="disabled",
            command=self.stop_bot,
        )
        self.btn_stop.grid(row=0, column=1, padx=(6, CARD_PAD), pady=(CARD_PAD, 6), sticky="ew")

        self.btn_open_log = ctk.CTkButton(
            card_controls,
            text="Error Log",
            height=34,
            font=ctk.CTkFont(size=13),
            fg_color=("gray50", "gray40"),
            hover_color=("gray40", "gray35"),
            corner_radius=10,
            command=self._open_autoloot_log,
        )
        self.btn_open_log.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=CARD_PAD,
            pady=(0, CARD_PAD),
            sticky="ew",
        )

        # Status bar
        status_frame = ctk.CTkFrame(self, fg_color=("gray18", "gray14"), height=40, corner_radius=0)
        status_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Ready",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=PAD, pady=10)

    # ── License helpers ───────────────────────────────────────────────────────

    _DOT_COLORS = {
        LicenseState.VALID:       "#22c55e",   # green
        LicenseState.VALIDATING:  "#f59e0b",   # yellow
        LicenseState.RETRYING:    "#f59e0b",   # yellow
        LicenseState.INVALID:     "#ef4444",   # red
        LicenseState.EMPTY:       "#ef4444",   # red
        LicenseState.STALE:       "#ef4444",   # red
        LicenseState.UNREACHABLE: "#ef4444",   # red
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
        color = self._DOT_COLORS.get(state, "#ef4444")
        self._main_lic_indicator.itemconfig(self._main_lic_dot, fill=color)
        dlg = self._active_license_dialog()
        if dlg is not None:
            dlg.paint_dot_color(color)

    def _license_status_caption(self, state: LicenseState) -> tuple[str, str]:
        if state == LicenseState.VALID:
            return ("Licensed.", RUN_GREEN)
        if state == LicenseState.VALIDATING:
            text, color = ("Checking license…", "#fbbf24")
        elif state == LicenseState.RETRYING:
            text, color = ("Reconnecting to license server…", "#fbbf24")
        elif state == LicenseState.STALE:
            text, color = (
                "You edited the key since it was last validated. Click Check Key below to verify.",
                TEXT_MUTED,
            )
        elif state == LicenseState.EMPTY:
            text, color = (
                "No license yet. Paste your key below, then Check Key.",
                TEXT_MUTED,
            )
        elif state in (LicenseState.INVALID, LicenseState.UNREACHABLE):
            text, color = (self._license_mgr.user_message, DANGER)
        else:
            text, color = ("Unknown license status.", TEXT_MUTED)
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
        """Main window line: subscription/lifetime expiry when licensed; trial countdown otherwise."""
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
            line = _format_license_expires_on_line(sub_raw) if sub_raw else ""
            if line:
                lbl.configure(text=line)
                lbl.grid(row=0, column=3, sticky="w", padx=(10, 0))
            elif lbl.grid_info():
                lbl.grid_remove()
            return

        rs = self._trial_remaining_seconds
        if rs is not None and rs > 0:
            lbl.configure(text=_format_trial_expires_in_minutes(rs))
            lbl.grid(row=0, column=3, sticky="w", padx=(10, 0))
        elif lbl.grid_info():
            lbl.grid_remove()

    def _on_license_state_change(self, state: LicenseState, reason: str) -> None:
        """Called from the background LicenseManager thread — marshal to Tk."""
        self.after(0, lambda s=state, r=reason: self._apply_license_state(s, r))

    def _apply_license_state(self, state: LicenseState, reason: str) -> None:
        """Update the UI for the new license state (runs on Tk thread)."""
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

        # Mid-session: cancel trial scheduler when a valid license is confirmed.
        if state == LicenseState.VALID and self._trial_tick_job is not None:
            self._flush_trial_heartbeat()

        # Mid-session: if the bot is running and the key goes invalid, stop it
        if state in (LicenseState.INVALID, LicenseState.UNREACHABLE):
            if self.bot_thread and self.bot_thread.is_alive():
                reason_msg = self._license_mgr.user_message
                self.stop_bot()
                messagebox.showerror(
                    "License Revoked",
                    f"The bot has been stopped.\n\n{reason_msg}",
                )

    # ── End license helpers ───────────────────────────────────────────────────

    def _setup_taskbar_thumb(self):
        """Initialize taskbar thumbnail toolbar (Windows only)."""
        if not TaskbarThumb or self._taskbar_thumb:
            return
        self.update_idletasks()  # Ensure window is realized and title is set
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
            logger.warning(f"Taskbar thumb setup failed: {e}", exc_info=True)
            self._taskbar_thumb = None

    def _on_taskbar_start(self):
        if not (self.bot_thread and self.bot_thread.is_alive()):
            self.start_bot()

    def _on_taskbar_stop(self):
        if self.bot_thread and self.bot_thread.is_alive():
            self.stop_bot()

    def _validate_duration(self, value):
        """Allow only digits, max 3 characters."""
        if value == "":
            return True
        return len(value) <= 3 and value.isdigit()

    def _on_star_bonus_toggle(self):
        grey = "gray40"
        if self.star_bonus_switch.get():
            self.entry_minutes.configure(state="disabled", text_color=grey)
            self.label_duration.configure(text_color=grey)
            self.label_minutes.configure(text_color=grey)
            self.btn_5m.configure(state="disabled")
            self.btn_10m.configure(state="disabled")
            self.btn_20m.configure(state="disabled")
        else:
            self.entry_minutes.configure(state="normal", text_color=("gray10", "gray90"))
            self.label_duration.configure(text_color=TEXT_MUTED)
            self.label_minutes.configure(text_color=TEXT_MUTED)
            self.btn_5m.configure(state="normal")
            self.btn_10m.configure(state="normal")
            self.btn_20m.configure(state="normal")

    def _on_upgrade_walls_toggle(self):
        now = time.monotonic()
        self._upgrade_walls_toggle_times.append(now)
        cutoff = now - 2.0
        self._upgrade_walls_toggle_times = [
            t for t in self._upgrade_walls_toggle_times if t >= cutoff
        ]
        if len(self._upgrade_walls_toggle_times) >= 6:
            self._maybe_show_upgrade_walls_debug_button()
            self._upgrade_walls_toggle_times.clear()

    def _maybe_show_upgrade_walls_debug_button(self):
        if self._upgrade_walls_debug_visible:
            return
        self._upgrade_walls_debug_visible = True
        self.btn_debug_upgrade_walls.grid(row=3, column=0, sticky="w", pady=(8, 0))
        logger.info("Upgrade walls debug button revealed (6 toggles in 2s)")

    def _debug_upgrade_walls_click(self):
        if self.bot_thread and self.bot_thread.is_alive():
            messagebox.showwarning(
                "Bot running",
                "Stop the bot before running debug wall upgrade.",
                parent=self,
            )
            return

        self.btn_debug_upgrade_walls.configure(state="disabled")
        self.status_label.configure(text="Debug: upgrading walls…", text_color=TEXT_MUTED)

        def worker():
            err: Optional[str] = None
            try:
                self.bot.debug_upgrade_walls_now()
            except Exception as e:
                err = str(e)
                logger.exception("debug_upgrade_walls_now")

            def done():
                self.btn_debug_upgrade_walls.configure(state="normal")
                if err:
                    self.status_label.configure(
                        text=f"Debug walls failed: {err}", text_color=DANGER
                    )
                    messagebox.showerror("Debug walls", err, parent=self)
                else:
                    self.status_label.configure(
                        text="Debug wall upgrade finished", text_color=TEXT_MUTED
                    )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _set_minutes(self, value):
        self.entry_minutes.delete(0, "end")
        self.entry_minutes.insert(0, value)

    def _open_player_list(self):
        PlayerListDialog(self)

    def _multi_run_players_for_start(self):
        """Returns list for bot.start, or None if multi-run is off. Returns [] if invalid (caller shows error)."""
        if not self.multi_run_switch.get():
            return None
        players = load_players()
        if not any(p.enabled and p.name.strip() for p in players):
            return []
        return players

    def _get_method(self):
        return ATTACK_MAP.get(self.attack_choice.get(), 1)

    def _get_minutes(self):
        try:
            return int(self.entry_minutes.get() or "0")
        except ValueError:
            return 0

    def start_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            return

        # License gate — VALID skips trial check entirely.
        if self._license_mgr.state != LicenseState.VALID:
            if self._license_mgr.state == LicenseState.EMPTY:
                messagebox.showerror(
                    "No license",
                    "Checking trial balance…\n\nEnter a license key (License key…) to skip the trial.",
                )
            # Try trial probe; runs synchronously (short network hit).
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
            self.status_label.configure(text="Star Bonus...", text_color=TEXT_MUTED)
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
            self.status_label.configure(text="Running...", text_color=TEXT_MUTED)
            if self._taskbar_thumb:
                self._taskbar_thumb.update_buttons(running=True)
            self.bot_thread = threading.Thread(
                target=self._run_bot_thread,
                args=(method, mins, multi_arg),
                daemon=True,
            )
            self.bot_thread.start()

        # Start trial scheduler if not on a VALID license.
        if self._license_mgr.state != LicenseState.VALID:
            self._begin_trial_heartbeat_scheduler()

    def _run_star_bonus_thread(self, method, multi_run_players):
        def on_status(msg):
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
            )
            error_msg = None
        except Exception as e:
            error_msg = str(e)
        self.after(0, lambda: self._on_bot_finished(error_msg))

    def _run_bot_thread(self, method, mins, multi_run_players):
        def on_status(msg):
            self.after(0, lambda m=msg: self._update_status(m, warning="not found" in m.lower()))
        try:
            self.bot.start(
                method,
                mins,
                status_callback=on_status,
                multi_run_players=multi_run_players,
                ranked_fill=self.ranked_attack_switch.get(),
                upgrade_walls=self.upgrade_walls_switch.get(),
            )
            error_msg = None
        except Exception as e:
            error_msg = str(e)
        self.after(0, lambda: self._on_bot_finished(error_msg))

    def stop_bot(self):
        self._flush_trial_heartbeat()
        self.bot.stop()
        self.status_label.configure(text="Stopping...", text_color=TEXT_MUTED)

    def _update_status(self, msg: str, warning: bool = False):
        """Update status bar. Use warning=True for error styling."""
        color = DANGER if warning else TEXT_MUTED
        self.status_label.configure(text=msg, text_color=color)

    def _on_bot_finished(self, error_msg=None):
        self._flush_trial_heartbeat()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if self._taskbar_thumb:
            self._taskbar_thumb.update_buttons(running=False)
        if error_msg:
            preview = error_msg[:50] + "..." if len(error_msg) > 50 else error_msg
            self.status_label.configure(text=f"Error: {preview}", text_color="#ef4444")
            messagebox.showerror("Error", error_msg)
        else:
            self.status_label.configure(text="Stopped", text_color=TEXT_MUTED)
            try:
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass
        if self._license_mgr.state != LicenseState.VALID:
            self._schedule_trial_balance_probe()

    # ── Trial heartbeat scheduler ─────────────────────────────────────────────

    def _begin_trial_heartbeat_scheduler(self) -> None:
        """Kick off the 60-second Tk after() loop for trial debit."""
        self._trial_session += 1
        self._trial_last_mono = time.monotonic()
        session = self._trial_session
        self._trial_tick_job = self.after(TRIAL_HEARTBEAT_INTERVAL_MS, lambda: self._tick_trial(session))

    def _tick_trial(self, session: int) -> None:
        """Called every 60 s via Tk after(). Debit elapsed time; stop bot if exhausted."""
        if session != self._trial_session:
            return  # stale callback from a previous run
        if self._license_mgr.state == LicenseState.VALID:
            self._trial_tick_job = None
            return  # license became valid mid-session; no more trial needed

        now = time.monotonic()
        elapsed = int(now - self._trial_last_mono)
        self._trial_last_mono = now

        def _do_heartbeat(session_snap: int) -> None:
            result = send_trial_heartbeat(elapsed)
            if session_snap != self._trial_session:
                return  # superseded
            self.after(0, lambda r=result, s=session_snap: self._apply_trial_result(r, s))

        threading.Thread(target=_do_heartbeat, args=(session,), daemon=True).start()

    def _apply_trial_result(self, result: Any, session: int) -> None:
        """Marshal trial heartbeat result back to main thread."""
        if session != self._trial_session:
            return
        if not result.ok or result.remaining_seconds <= 0:
            self._trial_remaining_seconds = 0
            self._trial_tick_job = None
            self._trial_session += 1  # invalidate any in-flight callbacks
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
        # Re-arm the next tick.
        self._trial_tick_job = self.after(
            TRIAL_HEARTBEAT_INTERVAL_MS,
            lambda: self._tick_trial(session),
        )

    def _flush_trial_heartbeat(self) -> None:
        """Cancel the pending tick and send a final partial heartbeat in a daemon thread."""
        if self._trial_tick_job is not None:
            try:
                self.after_cancel(self._trial_tick_job)
            except Exception:
                pass
            self._trial_tick_job = None

        session_snap = self._trial_session
        self._trial_session += 1  # invalidate any in-flight _tick_trial callbacks

        if self._license_mgr.state == LicenseState.VALID:
            return  # nothing to flush for licensed users

        now = time.monotonic()
        elapsed = int(now - self._trial_last_mono)
        if elapsed <= 0:
            return

        def _flush(elapsed_: int) -> None:
            send_trial_heartbeat(elapsed_)

        threading.Thread(target=_flush, args=(elapsed,), daemon=True).start()


def _center_window(root):
    root.update_idletasks()
    w = root.winfo_reqwidth()
    h = root.winfo_reqheight()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    root.geometry(f"+{x}+{y}")


def run_gui():
    app = AutoLootApp()
    _center_window(app)
    app.mainloop()
