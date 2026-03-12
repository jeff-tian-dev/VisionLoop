import customtkinter as ctk
from tkinter import messagebox
import threading
import winsound
import platform
from app.core.bot import Bot
from app.utils.logger import setup_logger

logger = setup_logger("GUI")

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


class AutoLootApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Clash AutoLoot Bot")
        self.resizable(False, False)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.bot = Bot()
        self.bot_thread = None
        self._taskbar_thumb = None

        self._init_ui()

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

        # Card: Attack Method
        card_attack = self._card(main)
        card_attack.grid(row=1, column=0, sticky="ew", pady=(0, 8))
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
        card_options.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        card_options.grid_columnconfigure(0, weight=1)

        # Options (switches stacked)
        opt_row = ctk.CTkFrame(card_options, fg_color="transparent")
        opt_row.grid(row=0, column=0, sticky="ew", padx=CARD_PAD, pady=(CARD_PAD, 6))
        opt_row.grid_columnconfigure(0, weight=1)

        self.wall_switch = ctk.CTkSwitch(
            opt_row,
            text="Auto Upgrade Walls",
            font=ctk.CTkFont(size=13),
            onvalue=True,
            offvalue=False,
        )
        self.wall_switch.grid(row=0, column=0, sticky="w")

        self.star_bonus_switch = ctk.CTkSwitch(
            opt_row,
            text="Star Bonus",
            font=ctk.CTkFont(size=13),
            onvalue=True,
            offvalue=False,
            command=self._on_star_bonus_toggle,
        )
        self.star_bonus_switch.grid(row=1, column=0, sticky="w", pady=(8, 0))

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

        # Card: Controls
        card_controls = self._card(main)
        card_controls.grid(row=3, column=0, sticky="ew", pady=(0, 8))
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
        self.btn_start.grid(row=0, column=0, padx=(CARD_PAD, 6), pady=CARD_PAD, sticky="ew")

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
        self.btn_stop.grid(row=0, column=1, padx=(6, CARD_PAD), pady=CARD_PAD, sticky="ew")

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

    def _set_minutes(self, value):
        self.entry_minutes.delete(0, "end")
        self.entry_minutes.insert(0, value)

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

        method = self._get_method()
        walls = self.wall_switch.get()

        if self.star_bonus_switch.get():
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.status_label.configure(text="Star Bonus...", text_color=TEXT_MUTED)
            if self._taskbar_thumb:
                self._taskbar_thumb.update_buttons(running=True)
            self.bot_thread = threading.Thread(
                target=self._run_star_bonus_thread,
                args=(method, walls),
                daemon=True,
            )
            self.bot_thread.start()
        else:
            mins = self._get_minutes()
            if mins <= 0 or mins > 999:
                messagebox.showerror("Error", "Invalid time duration. Enter 1-999 minutes.")
                return

            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.status_label.configure(text="Running...", text_color=TEXT_MUTED)
            if self._taskbar_thumb:
                self._taskbar_thumb.update_buttons(running=True)
            self.bot_thread = threading.Thread(
                target=self._run_bot_thread,
                args=(method, mins, walls),
                daemon=True,
            )
            self.bot_thread.start()

    def _run_star_bonus_thread(self, method, walls):
        def on_status(msg):
            self.after(0, lambda m=msg: self._update_status(m, warning="not found" in m.lower()))
        try:
            self.bot.start(method, 5, walls, star_bonus=True, status_callback=on_status)
            error_msg = None
        except Exception as e:
            error_msg = str(e)
        self.after(0, lambda: self._on_bot_finished(error_msg))

    def _run_bot_thread(self, method, mins, walls):
        def on_status(msg):
            self.after(0, lambda m=msg: self._update_status(m, warning="not found" in m.lower()))
        try:
            self.bot.start(method, mins, walls, status_callback=on_status)
            error_msg = None
        except Exception as e:
            error_msg = str(e)
        self.after(0, lambda: self._on_bot_finished(error_msg))

    def stop_bot(self):
        self.bot.stop()
        self.status_label.configure(text="Stopping...", text_color=TEXT_MUTED)

    def _update_status(self, msg: str, warning: bool = False):
        """Update status bar. Use warning=True for error styling."""
        color = DANGER if warning else TEXT_MUTED
        self.status_label.configure(text=msg, text_color=color)

    def _on_bot_finished(self, error_msg=None):
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
