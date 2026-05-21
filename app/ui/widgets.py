from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk
from tkinter import Label, Toplevel
from tkinter import Canvas as TkCanvas

from app.ui import theme as t


def format_license_expires_on_line(sub: str) -> str:
    """Normalize subscription/lifetime line to start with 'Expires on:'."""
    s = sub.strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("expires on:"):
        rest = s.split(":", 1)[1].strip()
        return f"Expires on: {rest}"
    return f"Expires on: {s}"


def format_trial_expires_in_minutes(remaining_seconds: int) -> str:
    mins = max(1, (int(remaining_seconds) + 59) // 60)
    unit = "minute" if mins == 1 else "minutes"
    return f"Expires in: {mins} {unit}"


class Tooltip:
    """Themed tooltip after a hover delay; allows moving onto the balloon to read."""

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


def card(parent: Any, **kwargs: Any) -> ctk.CTkFrame:
    """Card-style frame with border and rounded corners."""
    kw = dict(
        fg_color=t.CARD_FG,
        corner_radius=t.RADIUS,
        border_width=1,
        border_color=t.BORDER,
    )
    kw.update(kwargs)
    return ctk.CTkFrame(parent, **kw)


def section_title(parent: Any, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(size=t.FONT_SECTION, weight="bold"),
        text_color=t.COLOR_TEXT_MUTED,
        anchor="w",
    )


def primary_button(
    parent: Any, *, text: str, command: Callable[[], None], height: int = t.H_MD, **kw: Any
) -> ctk.CTkButton:
    font = kw.pop("font", ctk.CTkFont(size=t.FONT_BUTTON))
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        font=font,
        fg_color=t.COLOR_PRIMARY,
        hover_color=t.COLOR_PRIMARY_HOV,
        **kw,
    )


def danger_button(
    parent: Any, *, text: str, command: Callable[[], None], height: int = t.H_MD, **kw: Any
) -> ctk.CTkButton:
    font = kw.pop("font", ctk.CTkFont(size=t.FONT_BUTTON))
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        font=font,
        fg_color=t.COLOR_DANGER,
        hover_color=t.COLOR_DANGER_HOV,
        **kw,
    )


def neutral_button(
    parent: Any, *, text: str, command: Callable[[], None], height: int = t.H_MD, **kw: Any
) -> ctk.CTkButton:
    font = kw.pop("font", ctk.CTkFont(size=t.FONT_BUTTON))
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        font=font,
        fg_color=t.COLOR_NEUTRAL,
        hover_color=t.COLOR_NEUTRAL_HOV,
        **kw,
    )


def small_chip_button(
    parent: Any, *, text: str, command: Callable[[], None], width: int = 48, **kw: Any
) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        width=width,
        height=t.H_SM,
        font=ctk.CTkFont(size=t.FONT_BUTTON),
        fg_color=t.COLOR_NEUTRAL_DARK,
        hover_color=t.COLOR_NEUTRAL_DARK_HOV,
        **kw,
    )


class StatusDot:
    """14×14 canvas status indicator."""

    def __init__(self, parent: Any, *, bg: str = "#1a1a1a") -> None:
        self._canvas = TkCanvas(parent, width=14, height=14, bg=bg, highlightthickness=0)
        self._item = self._canvas.create_oval(2, 2, 12, 12, fill="#ef4444", outline="")

    @property
    def canvas(self) -> TkCanvas:
        return self._canvas

    def grid(self, **kwargs: Any) -> None:
        self._canvas.grid(**kwargs)

    def set_color(self, color: str) -> None:
        self._canvas.itemconfig(self._item, fill=color)
