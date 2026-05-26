"""Run page — attack, schedule, modes, controls."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import check_game_window_aspect_for_start
from app.services.license import LicenseState
from app.services.trial import TRIAL_TOTAL_SECONDS, fetch_trial_status
from app.ui.qt._constants import ATTACK_STRATEGIES
from app.ui.qt.bot_controller import BotController
from app.ui.qt.dialogs import RankedAttackConfirmDialog, show_error
from app.ui.qt.theme import SPACING, TOKENS
from app.ui.qt.widgets import (
    Card,
    SectionTitle,
    StepperButton,
    ToggleSwitch,
    chip_button,
    danger_button,
    neutral_button,
    primary_button,
    segment_button,
)
from app.utils.common import get_autoloot_log_path
from app.utils.player_list_store import PlayerEntry, load_players


class RunPage(QWidget):
    _STRATEGY_LABELS = ["Valkyries", "Sneaky Goblins", "Super Minions", "Edrags"]

    def __init__(
        self,
        controller: BotController,
        navigate_to: Callable[[str], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._navigate_to = navigate_to

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["md"])

        layout.addWidget(self._build_attack_card())
        layout.addWidget(self._build_schedule_card())
        layout.addWidget(self._build_modes_card())
        layout.addWidget(self._build_controls_card())
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._controller.botStarted.connect(self._on_bot_started)
        self._controller.botFinished.connect(self._on_bot_finished_ui)
        self._controller.runningChanged.connect(self._on_running_changed)

    def _build_attack_card(self) -> Card:
        card = Card()
        card.card_layout.addWidget(SectionTitle("Attack Strategy"))
        row = QHBoxLayout()
        self._strategy_group = QButtonGroup(self)
        self._strategy_group.setExclusive(True)
        for i, label in enumerate(self._STRATEGY_LABELS):
            btn = segment_button(label, parent=card)
            if label == "Valkyries":
                btn.setChecked(True)
            self._strategy_group.addButton(btn, i)
            row.addWidget(btn)
        card.card_layout.addLayout(row)
        return card

    def _build_schedule_card(self) -> Card:
        card = Card()
        card.card_layout.addWidget(SectionTitle("Schedule"))
        self._star_bonus = ToggleSwitch("Star Bonus", parent=card)
        self._star_bonus.toggled.connect(self._on_star_bonus_toggle)
        card.card_layout.addWidget(self._star_bonus)

        dur_row = QHBoxLayout()
        self._duration_label = SectionTitle("Duration")
        dur_row.addWidget(self._duration_label)

        self._minutes_spin = QSpinBox()
        self._minutes_spin.setObjectName("DurationSpin")
        self._minutes_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._minutes_spin.setRange(1, 999)
        self._minutes_spin.setValue(15)
        self._minutes_spin.setFixedSize(56, 28)
        self._minutes_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)

        step_col = QVBoxLayout()
        step_col.setSpacing(2)
        step_col.setContentsMargins(0, 0, 0, 0)
        self._btn_spin_up = StepperButton(up=True, parent=card)
        self._btn_spin_up.clicked.connect(lambda: self._step_minutes(1))
        self._btn_spin_down = StepperButton(up=False, parent=card)
        self._btn_spin_down.clicked.connect(lambda: self._step_minutes(-1))
        step_col.addWidget(self._btn_spin_up)
        step_col.addWidget(self._btn_spin_down)

        self._minutes_unit = QLabel("minutes")
        self._minutes_unit.setStyleSheet(f"color: {TOKENS['text_muted']};")

        spin_group = QHBoxLayout()
        spin_group.setSpacing(4)
        spin_group.addWidget(self._minutes_spin)
        spin_group.addLayout(step_col)
        spin_group.addWidget(self._minutes_unit)
        spin_group.addStretch()
        dur_row.addLayout(spin_group)
        dur_row.addStretch()
        card.card_layout.addLayout(dur_row)

        preset_row = QHBoxLayout()
        self._btn_5m = chip_button("5m", parent=card)
        self._btn_5m.clicked.connect(lambda: self._set_minutes(5))
        preset_row.addWidget(self._btn_5m)
        self._btn_10m = chip_button("10m", parent=card)
        self._btn_10m.clicked.connect(lambda: self._set_minutes(10))
        preset_row.addWidget(self._btn_10m)
        self._btn_20m = chip_button("20m", parent=card)
        self._btn_20m.clicked.connect(lambda: self._set_minutes(20))
        preset_row.addWidget(self._btn_20m)
        preset_row.addStretch()
        card.card_layout.addLayout(preset_row)
        return card

    def _build_modes_card(self) -> Card:
        card = Card()
        card.card_layout.addWidget(SectionTitle("Modes"))
        self._ranked = ToggleSwitch("Ranked attack fill", parent=card, danger=True)
        card.card_layout.addWidget(self._ranked)
        self._upgrade_walls = ToggleSwitch("Upgrade walls", parent=card)
        card.card_layout.addWidget(self._upgrade_walls)

        mr_row = QHBoxLayout()
        self._multi_run = ToggleSwitch("Multi-run", parent=card)
        mr_row.addWidget(self._multi_run)
        mr_row.addStretch()
        edit_players = neutral_button("Edit player list", parent=card)
        edit_players.clicked.connect(lambda: self._navigate_to("players"))
        mr_row.addWidget(edit_players)
        card.card_layout.addLayout(mr_row)
        return card

    def _build_controls_card(self) -> Card:
        card = Card()
        btn_row = QHBoxLayout()
        self._btn_start = primary_button("Start", parent=card)
        self._btn_start.setMinimumHeight(42)
        self._btn_start.clicked.connect(self.start_bot)
        btn_row.addWidget(self._btn_start)
        self._btn_stop = danger_button("Stop", parent=card)
        self._btn_stop.setMinimumHeight(42)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._controller.stop)
        btn_row.addWidget(self._btn_stop)
        card.card_layout.addLayout(btn_row)

        self._btn_log = neutral_button("Error Log", parent=card)
        self._btn_log.clicked.connect(self._open_autoloot_log)
        card.card_layout.addWidget(self._btn_log)
        return card

    def _clear_minutes_selection(self) -> None:
        editor = self._minutes_spin.lineEdit()
        if editor is not None:
            editor.deselect()
            editor.setCursorPosition(len(editor.text()))

    def _step_minutes(self, delta: int) -> None:
        if delta > 0:
            self._minutes_spin.stepUp()
        else:
            self._minutes_spin.stepDown()
        self._clear_minutes_selection()
        QTimer.singleShot(0, self._clear_minutes_selection)

    def _set_minutes(self, value: int) -> None:
        self._minutes_spin.setValue(value)
        self._clear_minutes_selection()

    def _on_star_bonus_toggle(self, checked: bool) -> None:
        enabled = not checked
        self._minutes_spin.setEnabled(enabled)
        self._duration_label.setEnabled(enabled)
        self._btn_spin_up.setEnabled(enabled)
        self._btn_spin_down.setEnabled(enabled)
        self._minutes_unit.setEnabled(enabled)
        self._btn_5m.setEnabled(enabled)
        self._btn_10m.setEnabled(enabled)
        self._btn_20m.setEnabled(enabled)

    def _get_method(self) -> int:
        btn = self._strategy_group.checkedButton()
        if btn is None:
            return ATTACK_STRATEGIES["Valkyries"]
        return ATTACK_STRATEGIES.get(btn.text(), 1)

    def _get_minutes(self) -> int:
        return self._minutes_spin.value()

    def _multi_run_players_for_start(self) -> Optional[List[PlayerEntry]]:
        if not self._multi_run.isChecked():
            return None
        players = load_players()
        if not any(p.enabled and p.name.strip() for p in players):
            return []
        return players

    def start_bot(self) -> None:
        if self._controller.is_running():
            return

        if self._controller.license_state() != LicenseState.VALID:
            if self._controller.license_state() == LicenseState.EMPTY:
                show_error(
                    self.window(),
                    "No license",
                    "Checking trial balance…\n\nEnter a license key (License key…) to skip the trial.",
                )
            result = fetch_trial_status()
            if not result.allowed:
                mins = TRIAL_TOTAL_SECONDS // 60
                show_error(
                    self.window(),
                    "Trial expired",
                    f"Your {mins}-minute free trial has been used up.\n\n"
                    "Check Key with a valid license key or purchase one to keep using the bot.",
                )
                return
            self._controller.apply_trial_balance_for_start(result)

        if not check_game_window_aspect_for_start(parent=self.window()):
            return

        method = self._get_method()
        multi_arg = self._multi_run_players_for_start()
        if self._multi_run.isChecked() and not multi_arg:
            show_error(
                self.window(),
                "Multi-run",
                "Enable at least one player with Run and a non-empty name.\nOpen Player list… to edit.",
            )
            return

        star_bonus = self._star_bonus.isChecked()
        if not star_bonus:
            mins = self._get_minutes()
            if mins <= 0 or mins > 999:
                show_error(self.window(), "Error", "Invalid time duration. Enter 1-999 minutes.")
                return
        else:
            mins = 5

        if self._ranked.isChecked():
            confirm_mins = self._get_minutes()
            if not RankedAttackConfirmDialog.ask(self.window(), confirm_mins):
                return

        self._controller.start(
            method=method,
            minutes=mins,
            star_bonus=star_bonus,
            ranked_fill=self._ranked.isChecked(),
            upgrade_walls=self._upgrade_walls.isChecked(),
            multi_run_players=multi_arg,
        )

    def is_star_bonus_enabled(self) -> bool:
        return self._star_bonus.isChecked()

    def request_start_from_taskbar(self) -> None:
        if not self._controller.is_running():
            self.start_bot()

    def request_stop_from_taskbar(self) -> None:
        if self._controller.is_running():
            self._controller.stop()

    def _on_bot_started(self) -> None:
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)

    def _on_bot_finished_ui(self, _error) -> None:
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _on_running_changed(self, running: bool) -> None:
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)

    def _open_autoloot_log(self) -> None:
        path = get_autoloot_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.touch()
        except OSError as exc:
            show_error(self.window(), "Log file", f"Could not create log file:\n{path}\n\n{exc}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except OSError as exc:
            show_error(self.window(), "Log file", f"Could not open log:\n{path}\n\n{exc}")
