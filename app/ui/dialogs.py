"""Modal and auxiliary windows for the main app."""

from __future__ import annotations

import threading
import webbrowser
from typing import Any, Dict, List, Optional

import customtkinter as ctk
from tkinter import messagebox

from app.services.license import LicenseState, clear_saved_key, load_saved_key
from app.utils.player_list_store import PlayerEntry, load_players, save_players
from app.utils.profile_settings_store import (
    EARTHQUAKE_METHOD_OPTIONS,
    ProfileSettings,
    load_profile_settings,
    save_profile_settings,
)

from app.ui import theme as t
from app.ui.widgets import (
    StatusDot,
    Tooltip,
    card,
    danger_button,
    neutral_button,
    primary_button,
)


class PlayerListDialog(ctk.CTkToplevel):
    """Edit multi-run player order, names, and Run/Skip per row."""

    def __init__(self, master: Any) -> None:
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
            text_color=t.COLOR_TEXT_MUTED,
            wraplength=520,
            justify="left",
        )
        hint.pack(anchor="w", padx=t.PAD_OUTER, pady=(t.PAD_OUTER, t.SPACE_SM))

        self.scroll = ctk.CTkScrollableFrame(self, width=520, height=280)
        self.scroll.pack(fill="both", expand=True, padx=t.PAD_OUTER, pady=(0, t.SPACE_SM))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=t.PAD_OUTER, pady=(0, t.PAD_OUTER))
        ctk.CTkButton(bottom, text="Add player", width=100, command=self._add_empty_row).pack(
            side="left"
        )
        primary_button(
            bottom, text="Done", command=self._on_done, width=100
        ).pack(side="right")

        for p in load_players():
            self._add_row(p.name, p.enabled)
        if not self._rows:
            self._add_empty_row()

        self.protocol("WM_DELETE_WINDOW", self._on_done)

    def _apply_mode_colors(self, mode: ctk.CTkSegmentedButton) -> None:
        if mode.get() == "Run":
            mode.configure(
                selected_color=t.COLOR_SUCCESS, selected_hover_color=t.COLOR_SUCCESS_HOV
            )
        else:
            mode.configure(selected_color=t.COLOR_DANGER, selected_hover_color=t.COLOR_DANGER_HOV)

    def _add_empty_row(self) -> None:
        self._add_row("", True)

    def _reflow_rows(self) -> None:
        for r in self._rows:
            r["frame"].pack_forget()
        for r in self._rows:
            r["frame"].pack(fill="x", pady=t.SPACE_XS)

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
        row_f.pack(fill="x", pady=t.SPACE_XS)

        entry = ctk.CTkEntry(row_f, width=210, placeholder_text="Username (match in-game)")
        if name:
            entry.insert(0, name)
        entry.pack(side="left", padx=(0, t.SPACE_SM))
        entry.bind("<FocusOut>", lambda _e: self._save())
        entry.bind("<Return>", lambda _e: self._save())

        mode = ctk.CTkSegmentedButton(row_f, values=["Run", "Skip"], width=118, height=t.H_SM)
        mode.set("Run" if enabled else "Skip")

        def on_change(_v: str) -> None:
            self._apply_mode_colors(mode)
            self._save()

        mode.configure(command=on_change)
        self._apply_mode_colors(mode)
        mode.pack(side="left", padx=(0, t.SPACE_SM))

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
        ).pack(side="left", padx=(0, t.SPACE_SM))

        def remove() -> None:
            self._rows = [r for r in self._rows if r["frame"] is not row_f]
            row_f.destroy()
            self._save()

        danger_button(row_f, text="Remove", width=72, command=remove).pack(side="left")

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


class ProfileSettingsDialog(ctk.CTkToplevel):
    """Edit profile settings stored as ``settings.json`` in app data."""

    def __init__(self, master: Any) -> None:
        super().__init__(master)
        self.title("Settings")
        self.geometry("400x190")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        s = load_profile_settings()

        ctk.CTkLabel(
            self,
            text="Earthquake Method",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=t.COLOR_TEXT_MUTED,
        ).pack(anchor="w", padx=t.PAD_OUTER, pady=(t.PAD_OUTER, t.SPACE_SM))

        self._earthquake = ctk.CTkOptionMenu(
            self,
            values=list(EARTHQUAKE_METHOD_OPTIONS),
            width=280,
            height=t.H_MD,
            font=ctk.CTkFont(size=t.FONT_BODY),
        )
        self._earthquake.set(s.earthquake_method)
        self._earthquake.pack(anchor="w", padx=t.PAD_OUTER, pady=(0, t.PAD_OUTER))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=t.PAD_OUTER, pady=(0, t.PAD_OUTER))
        ctk.CTkButton(row, text="Cancel", width=100, command=self.destroy).pack(side="right")
        primary_button(row, text="Save", command=self._on_save, width=100).pack(
            side="right", padx=(0, t.SPACE_SM)
        )

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_save(self) -> None:
        save_profile_settings(ProfileSettings(earthquake_method=self._earthquake.get()))
        self.destroy()


class RankedAttackConfirmDialog(ctk.CTkToplevel):
    """Modal confirm for ranked attack fill; Yes stays disabled for 5 seconds."""

    def __init__(self, master: Any, minutes: int):
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
            font=ctk.CTkFont(size=t.FONT_BODY),
            text_color=(t.COLOR_TEXT, t.COLOR_TEXT),
            wraplength=400,
            justify="left",
        ).pack(anchor="w", padx=t.PAD_OUTER, pady=(t.PAD_OUTER, t.SPACE_SM))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=t.PAD_OUTER, pady=(0, t.PAD_OUTER))

        self._remaining = 5
        self._btn_yes = danger_button(
            row,
            text="Yes (5)",
            command=self._on_yes,
            width=100,
            height=t.H_SM,
            state="disabled",
            font=ctk.CTkFont(size=t.FONT_BUTTON, weight="bold"),
        )
        self._btn_yes.pack(side="right", padx=(t.SPACE_SM, 0))
        neutral_button(row, text="No", command=self._on_no, width=100, height=t.H_SM).pack(
            side="right"
        )

        self.protocol("WM_DELETE_WINDOW", self._on_no)
        self._after_id = self.after(0, self._tick_countdown)
        self.after(10, self._place_over_parent)

    def _place_over_parent(self) -> None:
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
    def ask(master: Any, minutes: int) -> bool:
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
        self.configure(fg_color=t.COLOR_APP_BG)

        pad = t.PAD_OUTER
        ctk.CTkLabel(
            self,
            text=(
                "This will permanently remove THIS computer from your license binding on "
                "our server, and delete the license file saved under your Windows user folder.\n\n"
                "• You will need Check Key again later to reuse the same key.\n\n"
                "Copy your license key below if you need it for another PC or reinstall."
            ),
            font=ctk.CTkFont(size=12),
            text_color=t.COLOR_TEXT_MUTED,
            wraplength=t.UNPAIR_DIALOG_W - pad * 2,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=pad, pady=(pad, 12))

        ctk.CTkLabel(
            self,
            text="Your license key",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=t.COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", padx=pad)

        key_row = ctk.CTkFrame(self, fg_color="transparent")
        key_row.pack(fill="x", padx=pad, pady=(4, pad))
        key_row.grid_columnconfigure(0, weight=1)

        self._key_disp = ctk.CTkEntry(
            key_row,
            height=38,
            font=ctk.CTkFont(size=14, family=t.FONT_MONO),
        )
        self._key_disp.insert(0, self._snap)
        self._key_disp.configure(state="disabled")
        self._key_disp.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(
            key_row,
            text="Copy",
            width=80,
            height=38,
            command=self._copy_key,
        ).grid(row=0, column=1, padx=(t.SPACE_SM, 0))

        row_btns = ctk.CTkFrame(self, fg_color="transparent")
        row_btns.pack(fill="x", padx=pad, pady=(0, pad))

        neutral_button(
            row_btns, text="Cancel", width=100, height=t.H_SM, command=self._on_cancel
        ).pack(side="left")

        self._btn_unpair = danger_button(
            row_btns,
            text="Unpair this PC",
            width=150,
            height=t.H_SM,
            command=self._on_confirm_unpair,
        )
        self._btn_unpair.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        W, H = t.UNPAIR_DIALOG_W, t.UNPAIR_DIALOG_H
        self.geometry(f"{W}x{H}")
        self.after(12, lambda: self._center_on(license_dialog))

    def _center_on(self, parent: Any) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        parent.update_idletasks()
        W, H = t.UNPAIR_DIALOG_W, t.UNPAIR_DIALOG_H
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
                    msg = t.UNPAIR_USER_ERRORS.get(
                        reason_code, reason_code.replace("_", " ").title()
                    )
                    messagebox.showerror("Could not unpair", msg, parent=self._app)

            self._app.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()


class LicenseKeyDialog(ctk.CTkToplevel):
    """License-entry window (hidden via withdraw until opened from main UI)."""

    _LICENSE_STATUS_DEBOUNCE_MS = 200

    def __init__(self, app: Any):
        super().__init__(app)
        self._app = app
        self.title("License Key")
        self.resizable(False, False)
        self.transient(app)
        self.configure(fg_color=t.COLOR_APP_BG)

        card_f = card(self)
        card_f.pack(fill="both", expand=True, padx=t.PAD_OUTER, pady=t.PAD_OUTER)
        card_f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card_f,
            text=(
                "Edit your license key below. Nothing is saved or sent until you "
                "press Check Key — then the saved key file updates only if the "
                "server accepts it."
            ),
            font=ctk.CTkFont(size=12),
            text_color=t.COLOR_TEXT_MUTED,
            wraplength=400,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=t.CARD_PAD, pady=(t.CARD_PAD, t.SPACE_SM))

        self._status_text = ctk.CTkTextbox(
            card_f,
            width=t.LICENSE_STATUS_BODY_W,
            height=t.LICENSE_STATUS_BODY_H,
            font=ctk.CTkFont(size=t.FONT_BODY),
            text_color=t.COLOR_TEXT_MUTED,
            fg_color=t.CARD_FG,
            border_width=1,
            border_color=t.BORDER,
            corner_radius=t.RADIUS,
            activate_scrollbars=True,
            takefocus=False,
        )
        self._status_text.grid(row=1, column=0, sticky="ew", padx=t.CARD_PAD, pady=(0, t.SPACE_SM))
        self._status_text.insert("1.0", "")
        self._status_text.configure(state="disabled")

        lic_row = ctk.CTkFrame(card_f, fg_color="transparent")
        lic_row.grid(row=2, column=0, sticky="ew", padx=t.CARD_PAD, pady=(0, t.SPACE_XS))
        lic_row.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(
            lic_row,
            placeholder_text="CLASH-XXXX-XXXX-XXXX-XXXX",
            show="*",
            height=t.H_MD,
            font=ctk.CTkFont(size=t.FONT_BODY, family=t.FONT_MONO),
        )
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, t.SPACE_SM))
        self._entry.bind("<KeyRelease>", self._on_key_typed)

        self._show_var = False
        ctk.CTkButton(
            lic_row,
            text="👁",
            width=34,
            height=t.H_MD,
            fg_color=t.COLOR_NEUTRAL_DARK,
            hover_color=t.COLOR_NEUTRAL_DARK_HOV,
            command=self._toggle_visibility,
        ).grid(row=0, column=1, padx=(0, t.SPACE_SM))

        self._lic_dot = StatusDot(lic_row, bg="#1a1a1a")
        self._lic_dot.grid(row=0, column=2, padx=(0, t.SPACE_SM))
        Tooltip(self._lic_dot.canvas, app._license_indicator_tooltip_text)

        self._btn_activate = primary_button(
            lic_row,
            text="Check Key",
            command=self._on_check_key_clicked,
            width=108,
            height=t.H_MD,
        )
        self._btn_activate.grid(row=0, column=3)

        footer = ctk.CTkFrame(card_f, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=t.CARD_PAD, pady=(t.SPACE_XS, t.CARD_PAD))
        left_btns = ctk.CTkFrame(footer, fg_color="transparent")
        left_btns.pack(side="left")
        self._btn_monthly_extend = primary_button(
            left_btns,
            text="Buy / extend subscription",
            command=self._open_monthly_extend_checkout,
            width=174,
            height=t.H_SM,
            font=ctk.CTkFont(size=12),
        )
        self._btn_monthly_extend.pack(side="left", padx=(0, t.SPACE_SM))
        Tooltip(
            self._btn_monthly_extend,
            lambda: "Opens checkout for monthly access ($12 per month). Quantity = months. Paste your key "
            "there to extend, or leave blank for a new key.",
        )
        self._btn_lifetime = ctk.CTkButton(
            left_btns,
            text="Buy lifetime",
            width=118,
            height=t.H_SM,
            font=ctk.CTkFont(size=t.FONT_BUTTON),
            fg_color=t.COLOR_NEUTRAL_DARK,
            hover_color=t.COLOR_NEUTRAL_DARK_HOV,
            command=self._open_lifetime_checkout,
        )
        self._btn_lifetime.pack(side="left", padx=(0, t.SPACE_SM))
        Tooltip(
            self._btn_lifetime,
            lambda: "Opens Stripe Checkout for a one-time lifetime license.",
        )
        ctk.CTkButton(
            left_btns,
            text="Unpair…",
            width=100,
            height=t.H_SM,
            font=ctk.CTkFont(size=t.FONT_BUTTON),
            fg_color=t.COLOR_NEUTRAL_DARK,
            hover_color=t.COLOR_NEUTRAL_DARK_HOV,
            command=self._open_unpair_confirm,
        ).pack(side="left", padx=(10, 0))
        neutral_button(
            footer, text="Close", command=self._hide, width=100, height=t.H_SM
        ).pack(side="right")

        saved = load_saved_key()
        if saved:
            self._entry.insert(0, saved)

        self.geometry(f"{t.LICENSE_POPUP_W}x{t.LICENSE_POPUP_H}")
        self.minsize(t.LICENSE_POPUP_W, t.LICENSE_POPUP_H)
        self.maxsize(t.LICENSE_POPUP_W, t.LICENSE_POPUP_H)

        self.protocol("WM_DELETE_WINDOW", self._hide)
        self.after(10, lambda: self._place_over_parent(app))

        self._license_status_refresh_job: Optional[str] = None

    def _open_lifetime_checkout(self) -> None:
        url = (t.STRIPE_LIFETIME_URL or "").strip()
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
        url = (t.MONTH_EXTEND_CHECKOUT_URL or "").strip()
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
        W, H = t.LICENSE_POPUP_W, t.LICENSE_POPUP_H
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

    def _on_key_typed(self, _event: Any = None) -> None:
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
            self._lic_dot.set_color(color)

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
