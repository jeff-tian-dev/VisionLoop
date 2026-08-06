"""Run page — run plan, per-village settings, controls."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import check_game_window_aspect_for_start
from app.core.run_plan import BUILDER, HOME, VILLAGE_LABELS, VILLAGE_ORDER, RunPlan, VillageStep
from app.services.license import LicenseState
from app.services.trial import TRIAL_TOTAL_SECONDS, fetch_trial_status
from app.ui.qt._constants import (
    ATTACK_STRATEGIES,
    BUILDER_BASE_ATTACK_STRATEGIES,
    BUILDER_BASE_ATTACK_STRATEGIES_UNDER_DEV,
    BUILDER_BASE_PRIORITISE_LABELS,
)
from app.ui.qt.bot_controller import BotController
from app.ui.qt.dialogs import (
    RankedAttackConfirmDialog,
    show_bb_prioritise_help,
    show_error,
    show_under_development,
)
from app.ui.qt.theme import SPACING, TOKENS
from app.ui.qt.widgets import (
    Card,
    HelpButton,
    PageTitle,
    SectionTitle,
    StepperButton,
    ToggleSwitch,
    chip_button,
    danger_button,
    neutral_button,
    primary_button,
    segment_button,
)
from app.utils.player_list_store import load_players

# Third Include switch: collecting is not a village, so it has no settings panel.
COLLECT = "collect"
INCLUDE_KEYS = (HOME, BUILDER, COLLECT)
INCLUDE_LABELS = {**VILLAGE_LABELS, COLLECT: "Collect resources"}

# Star Bonus is capped at 15 minutes inside Bot.start(); the duration is ignored then.
STAR_BONUS_MINUTES = 15

# Display order of the strategy buttons (the constants dicts are keyed by method id).
_HOME_STRATEGY_LABELS = ["Valkyries", "Sneaky Goblins", "Super Minions", "Edrags"]
_HOME_STRATEGY_DEFAULT = "Valkyries"
_BUILDER_STRATEGY_LABELS = list(BUILDER_BASE_ATTACK_STRATEGIES)
_BUILDER_STRATEGY_DEFAULT = "Baby Dragons"


def _muted(text: str, *, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {TOKENS['text_muted']};")
    lbl.setWordWrap(wrap)
    return lbl


class _DurationRow(QWidget):
    """Duration spin box, stepper and presets for one village."""

    def __init__(self, minutes: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACING["sm"])

        row = QHBoxLayout()
        self._label = SectionTitle("Duration")
        row.addWidget(self._label)

        self._spin = QSpinBox()
        self._spin.setObjectName("DurationSpin")
        self._spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin.setRange(1, 999)
        self._spin.setValue(minutes)
        self._spin.setFixedSize(56, 28)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)

        steps = QVBoxLayout()
        steps.setSpacing(2)
        steps.setContentsMargins(0, 0, 0, 0)
        self._up = StepperButton(up=True, parent=self)
        self._up.clicked.connect(lambda: self._step(1))
        self._down = StepperButton(up=False, parent=self)
        self._down.clicked.connect(lambda: self._step(-1))
        steps.addWidget(self._up)
        steps.addWidget(self._down)

        self._unit = QLabel("minutes")
        self._unit.setObjectName("DurationUnit")
        self._unit.setStyleSheet(f"color: {TOKENS['text_muted']};")

        group = QHBoxLayout()
        group.setSpacing(4)
        group.addWidget(self._spin)
        group.addLayout(steps)
        group.addWidget(self._unit)
        group.addStretch()
        row.addLayout(group)
        row.addStretch()
        col.addLayout(row)

        presets = QHBoxLayout()
        self._chips: List[QPushButton] = []
        for m in (5, 10, 20):
            btn = chip_button(f"{m}m", parent=self)
            btn.clicked.connect(lambda _checked=False, mm=m: self.set_value(mm))
            presets.addWidget(btn)
            self._chips.append(btn)
        presets.addStretch()
        col.addLayout(presets)

    def _clear_selection(self) -> None:
        editor = self._spin.lineEdit()
        if editor is not None:
            editor.deselect()
            editor.setCursorPosition(len(editor.text()))

    def _step(self, delta: int) -> None:
        if delta > 0:
            self._spin.stepUp()
        else:
            self._spin.stepDown()
        self._clear_selection()
        QTimer.singleShot(0, self._clear_selection)

    def set_value(self, minutes: int) -> None:
        self._spin.setValue(minutes)
        self._clear_selection()

    def value(self) -> int:
        return self._spin.value()

    def set_enabled(self, enabled: bool) -> None:
        for widget in (self._label, self._spin, self._up, self._down, self._unit, *self._chips):
            widget.setEnabled(enabled)
        self._unit.setStyleSheet(f"color: {TOKENS['text_muted'] if enabled else '#4a5568'};")


class _VillagePanel(QWidget):
    """Attack strategy, schedule and modes for one village."""

    def __init__(
        self,
        village: str,
        on_include_requested: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._village = village

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACING["md"])

        self._excluded_banner = self._build_excluded_banner(on_include_requested)
        col.addWidget(self._excluded_banner)

        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACING["md"])
        body.addWidget(self._build_strategy_card())
        body.addWidget(self._build_schedule_card())
        body.addWidget(self._build_modes_card())
        col.addWidget(self._body)

        self.set_state(True, True)

    # -- cards ---------------------------------------------------------------

    def _build_excluded_banner(self, on_include_requested: Callable[[], None]) -> Card:
        card = Card()
        row = QHBoxLayout()
        name = VILLAGE_LABELS[self._village]
        self._excluded_text = _muted("", wrap=True)
        row.addWidget(self._excluded_text, stretch=1)
        include_btn = primary_button(f"Include {name}", parent=card)
        include_btn.clicked.connect(on_include_requested)
        row.addWidget(include_btn, alignment=Qt.AlignmentFlag.AlignTop)
        card.card_layout.addLayout(row)
        return card

    def _build_strategy_card(self) -> Card:
        card = Card()
        card.card_layout.addWidget(SectionTitle("Attack Strategy"))
        row = QHBoxLayout()
        self._strategy_group = QButtonGroup(self)
        self._strategy_group.setExclusive(True)
        if self._village == HOME:
            labels, default = _HOME_STRATEGY_LABELS, _HOME_STRATEGY_DEFAULT
        else:
            labels, default = _BUILDER_STRATEGY_LABELS, _BUILDER_STRATEGY_DEFAULT
        for i, label in enumerate(labels):
            btn = segment_button(label, parent=card)
            if label == default:
                btn.setChecked(True)
            self._strategy_group.addButton(btn, i)
            row.addWidget(btn)
        if self._village == BUILDER:
            for label in BUILDER_BASE_ATTACK_STRATEGIES_UNDER_DEV:
                btn = segment_button(label, parent=card, under_development=True)
                btn.clicked.connect(lambda _checked=False: show_under_development(self.window()))
                row.addWidget(btn)
        row.addStretch()
        card.card_layout.addLayout(row)
        return card

    def _build_schedule_card(self) -> Card:
        card = Card()
        card.card_layout.addWidget(SectionTitle("Schedule"))
        self._star = ToggleSwitch("Star Bonus", parent=card)
        self._star.toggled.connect(self._on_star_toggled)
        card.card_layout.addWidget(self._star)
        self._duration = _DurationRow(15 if self._village == HOME else 10, parent=card)
        card.card_layout.addWidget(self._duration)
        return card

    def _build_modes_card(self) -> Card:
        card = Card()
        card.card_layout.addWidget(SectionTitle("Modes"))
        if self._village == HOME:
            self._ranked = ToggleSwitch("Ranked attack fill", parent=card, danger=True)
            card.card_layout.addWidget(self._ranked)
            self._upgrade_walls = ToggleSwitch("Upgrade walls", parent=card)
            card.card_layout.addWidget(self._upgrade_walls)
            # Account rotation used to live here; it is global now, in Run plan.
        else:
            row = QHBoxLayout()
            row.addWidget(SectionTitle("Prioritise"))
            row.addWidget(
                HelpButton(lambda: show_bb_prioritise_help(self.window()), parent=card),
                alignment=Qt.AlignmentFlag.AlignVCenter,
            )
            row.addSpacing(SPACING["xs"])
            self._prioritise_group = QButtonGroup(self)
            self._prioritise_group.setExclusive(True)
            self._prioritise_buttons: Dict[str, QPushButton] = {}
            for i, label in enumerate(BUILDER_BASE_PRIORITISE_LABELS):
                btn = segment_button(label, parent=card)
                if label == "Both":
                    btn.setChecked(True)
                self._prioritise_group.addButton(btn, i)
                self._prioritise_buttons[label] = btn
                row.addWidget(btn)
            row.addStretch()
            card.card_layout.addLayout(row)
            card.card_layout.addWidget(
                ToggleSwitch("Upgrade walls", parent=card, under_development=True)
            )
        return card

    # -- state ---------------------------------------------------------------

    def _on_star_toggled(self, checked: bool) -> None:
        self._duration.set_enabled(not checked)
        self._apply_star_bonus_to_prioritise()

    def _apply_star_bonus_to_prioritise(self) -> None:
        """Builder Base: Elixir priority and Star Bonus cannot both hold.

        Prioritising Elixir surrenders each battle to farm elixir, which drops
        trophies, while the star bonus needs battle wins. So Star Bonus takes Elixir
        off the table and the choice falls back to Both; turning Star Bonus off
        re-opens Elixir without re-selecting it.
        """
        if self._village != BUILDER:
            return
        star_on = self._star.isChecked()
        elixir = self._prioritise_buttons["Elixir"]
        if star_on and elixir.isChecked():
            self._prioritise_buttons["Both"].setChecked(True)
        elixir.setEnabled(not star_on)
        elixir.setToolTip(
            "Star Bonus needs battle wins, and prioritising Elixir drops trophies."
            if star_on
            else ""
        )

    def set_state(self, included: bool, collecting: bool) -> None:
        """``included`` = this village is attacked; ``collecting`` = the global collect switch.

        An excluded village is still visited when collecting is on, so say so rather
        than claiming nothing will happen there.
        """
        name = VILLAGE_LABELS[self._village]
        if collecting:
            self._excluded_text.setText(
                f"{name} attacks are off for this run. Resources there will still be "
                f"collected. These settings are kept for when you include it."
            )
        else:
            self._excluded_text.setText(
                f"{name} is not part of this run. These settings are kept, "
                f"but nothing here will happen until you include it."
            )
        self._excluded_banner.setVisible(not included)
        self._body.setEnabled(included)
        # ToggleSwitch paints itself and ignores the disabled palette, so dim the
        # whole panel rather than relying on per-widget disabled styling.
        effect = None
        if not included:
            effect = QGraphicsOpacityEffect(self._body)
            effect.setOpacity(0.45)
        self._body.setGraphicsEffect(effect)

    def star_bonus(self) -> bool:
        return self._star.isChecked()

    def minutes(self) -> int:
        return self._duration.value()

    def method(self) -> int:
        btn = self._strategy_group.checkedButton()
        table = ATTACK_STRATEGIES if self._village == HOME else BUILDER_BASE_ATTACK_STRATEGIES
        default = _HOME_STRATEGY_DEFAULT if self._village == HOME else _BUILDER_STRATEGY_DEFAULT
        if btn is None:
            return table[default]
        return table.get(btn.text(), table[default])

    def ranked_fill(self) -> bool:
        return self._village == HOME and self._ranked.isChecked()

    def upgrade_walls(self) -> bool:
        return self._village == HOME and self._upgrade_walls.isChecked()

    def loot_prioritise(self) -> str:
        if self._village != BUILDER:
            return "both"
        btn = self._prioritise_group.checkedButton()
        return btn.text().lower() if btn is not None else "both"

    def to_step(self) -> VillageStep:
        star = self.star_bonus()
        minutes = STAR_BONUS_MINUTES if star else self.minutes()
        return VillageStep(
            village=self._village,
            method=self.method(),
            duration_seconds=minutes * 60,
            star_bonus=star,
            ranked_fill=self.ranked_fill(),
            upgrade_walls=self.upgrade_walls(),
            loot_prioritise=self.loot_prioritise(),
        )


class RunPage(QWidget):
    def __init__(
        self,
        controller: BotController,
        navigate_to: Callable[[str], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._navigate_to = navigate_to
        # Which Include switches were turned off, oldest first, so a run that would
        # end up empty can restore the one the user gave up first.
        self._off_order: List[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        outer.setSpacing(SPACING["md"])

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["md"])

        layout.addWidget(self._build_plan_card())
        layout.addWidget(self._build_village_tabs())

        self._panels: Dict[str, _VillagePanel] = {}
        for village in VILLAGE_ORDER:
            panel = _VillagePanel(
                village,
                on_include_requested=lambda v=village: self._include_switch(v).setChecked(True),
            )
            self._panels[village] = panel
            layout.addWidget(panel)

        layout.addWidget(self._build_controls_card())
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._select_village(HOME)
        self._refresh_plan()

        self._controller.botStarted.connect(self._on_bot_started)
        self._controller.botFinished.connect(self._on_bot_finished_ui)
        self._controller.runningChanged.connect(self._on_running_changed)

    # -- run plan card -------------------------------------------------------

    def _build_plan_card(self) -> Card:
        card = Card()
        title = QHBoxLayout()
        title.addWidget(PageTitle("Run plan"))
        title.addStretch()
        title.addWidget(HelpButton(self._show_plan_help, parent=card))
        card.card_layout.addLayout(title)
        card.card_layout.addWidget(
            _muted("Everything below is what one press of Start will do.", wrap=True)
        )
        card.card_layout.addSpacing(SPACING["xs"])

        acc_row = QHBoxLayout()
        acc_label = SectionTitle("Accounts")
        acc_label.setFixedWidth(72)
        acc_row.addWidget(acc_label)
        self._accounts_group = QButtonGroup(self)
        self._accounts_group.setExclusive(True)
        for i, label in enumerate(["This account only", "Rotate accounts"]):
            btn = segment_button(label, parent=card)
            if i == 0:
                btn.setChecked(True)
            self._accounts_group.addButton(btn, i)
            acc_row.addWidget(btn)
        self._accounts_group.idClicked.connect(lambda _i: self._refresh_plan())
        acc_row.addStretch(1)
        self._edit_players = neutral_button("Edit player list", parent=card)
        self._edit_players.clicked.connect(lambda: self._navigate_to("players"))
        acc_row.addWidget(self._edit_players)
        card.card_layout.addLayout(acc_row)

        inc_row = QHBoxLayout()
        inc_label = SectionTitle("Run")
        inc_label.setFixedWidth(72)
        inc_row.addWidget(inc_label)
        self._include_switches: Dict[str, ToggleSwitch] = {}
        for i, key in enumerate(INCLUDE_KEYS):
            if i:
                inc_row.addSpacing(SPACING["lg"])
            switch = ToggleSwitch(INCLUDE_LABELS[key], parent=card)
            switch.setChecked(True)
            switch.toggled.connect(lambda checked, k=key: self._on_include_toggled(k, checked))
            self._include_switches[key] = switch
            inc_row.addWidget(switch)
        inc_row.addStretch()
        card.card_layout.addLayout(inc_row)
        return card

    def _build_village_tabs(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_muted("Settings for:"))
        row.addSpacing(SPACING["sm"])
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tabs: Dict[str, QPushButton] = {}
        for i, village in enumerate(VILLAGE_ORDER):
            label = VILLAGE_LABELS[village]
            btn = segment_button(label, parent=wrapper)
            # Reserve room for the widest state so " · Off" never clips.
            btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(f"{label} · Off") + 40)
            self._tab_group.addButton(btn, i)
            self._tabs[village] = btn
            row.addWidget(btn)
        self._tab_group.idClicked.connect(lambda i: self._select_village(VILLAGE_ORDER[i]))
        row.addStretch()
        return wrapper

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
        return card

    # -- plan state ----------------------------------------------------------

    def _include_switch(self, key: str) -> ToggleSwitch:
        return self._include_switches[key]

    def _is_included(self, key: str) -> bool:
        return self._include_switches[key].isChecked()

    def _anything_included(self) -> bool:
        return any(self._is_included(k) for k in INCLUDE_KEYS)

    def _included_villages(self) -> List[str]:
        return [v for v in VILLAGE_ORDER if self._is_included(v)]

    def _rotating(self) -> bool:
        btn = self._accounts_group.checkedButton()
        return btn is not None and btn.text() == "Rotate accounts"

    def _on_include_toggled(self, key: str, checked: bool) -> None:
        if checked:
            if key in self._off_order:
                self._off_order.remove(key)
        elif key not in self._off_order:
            self._off_order.append(key)

        if key in self._panels and checked:
            self._select_village(key)

        if not self._anything_included():
            # A run with nothing in it would do nothing. Turn the earliest-off switch
            # back on; setChecked re-enters this handler, which clears it from
            # _off_order and restores its panel.
            restore = self._off_order[0] if self._off_order else HOME
            self._include_switch(restore).setChecked(True)

        self._refresh_plan()

    def _select_village(self, village: str) -> None:
        self._tabs[village].setChecked(True)
        for key, panel in self._panels.items():
            panel.setVisible(key == village)

    def _refresh_plan(self) -> None:
        collecting = self._is_included(COLLECT)
        for village in VILLAGE_ORDER:
            tab = self._tabs[village]
            label = VILLAGE_LABELS[village]
            included = self._is_included(village)
            self._panels[village].set_state(included, collecting)
            tab.setText(label if included else f"{label} · Off")
            # An excluded tab can still be the selected one — keep it visibly
            # selected, but never in the "active blue" that means "in the run".
            tab.setStyleSheet(
                ""
                if included
                else f"QPushButton:checked {{ background-color: {TOKENS['neutral']};"
                f" border-color: {TOKENS['neutral']}; color: {TOKENS['text_muted']}; }}"
            )
        self._edit_players.setVisible(self._rotating())

    def _show_plan_help(self) -> None:
        QMessageBox.information(
            self.window(),
            "Run plan",
            "A run is one pass through this plan.\n\n"
            "• Accounts — 'Rotate accounts' logs into each account marked Run on the "
            "Players page, in list order, and gives each one the whole plan below.\n\n"
            "• Run — Home Village and Builder Base decide where the run attacks. "
            "Each uses its own strategy and duration; switch between them with the "
            "tabs underneath.\n\n"
            "• Collect resources — taps the gold/elixir bubbles and the clock boost "
            "in both villages, including one whose attacks are off.\n\n"
            "Turning something off keeps its settings, it just skips it this run. "
            "A run can't be empty, so turning off the last one switches an earlier "
            "one back on.",
        )

    # -- start ---------------------------------------------------------------

    def build_plan(self) -> RunPlan:
        steps = tuple(self._panels[v].to_step() for v in self._included_villages())
        players = tuple(load_players()) if self._rotating() else None
        return RunPlan(
            steps=steps,
            collect_resources=self._is_included(COLLECT),
            players=players,
        )

    def _confirm_bb_elixir_prioritise(self) -> bool:
        reply = QMessageBox.warning(
            self.window(),
            "Elixir priority",
            "Prioritising Elixir will deplete your trophies.\n\nDo you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _confirm_rotation(self, plan: RunPlan) -> bool:
        names = [p.name for p in plan.enabled_players]
        lines = []
        for step in plan.steps:
            when = "until star bonus" if step.star_bonus else f"{step.duration_seconds // 60} min"
            lines.append(f"      {step.label} — {when}")
        if not lines:
            lines.append("      Collect resources only — no attacks")
        body = "\n".join(f"  {i}. {name}\n" + "\n".join(lines) for i, name in enumerate(names, 1))
        tail = (
            "\n\nResources are collected on the way through."
            if plan.collect_resources
            else "\n\nResource collection is off — nothing will be tapped to collect."
        )
        box = QMessageBox(self.window())
        box.setWindowTitle("Start run")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"This run will farm {len(names)} accounts in order:")
        box.setInformativeText(body + tail)
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        box.button(QMessageBox.StandardButton.Ok).setText("Start run")
        return box.exec() == QMessageBox.StandardButton.Ok

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

        if not check_game_window_aspect_for_start(
            parent=self.window(),
            on_configure=lambda: self._navigate_to("settings"),
        ):
            return

        plan = self.build_plan()

        if plan.rotating and not plan.enabled_players:
            show_error(
                self.window(),
                "Rotate accounts",
                "Enable at least one player with Run and a non-empty name.\n"
                "Open the Players page to edit the list.",
            )
            return

        for step in plan.steps:
            if step.star_bonus:
                continue
            minutes = step.duration_seconds // 60
            if minutes <= 0 or minutes > 999:
                show_error(
                    self.window(),
                    "Error",
                    f"Invalid {step.label} duration. Enter 1-999 minutes.",
                )
                return

        home_step = plan.step_for(HOME)
        if home_step is not None and home_step.ranked_fill:
            if not RankedAttackConfirmDialog.ask(self.window(), home_step.duration_seconds // 60):
                return

        builder_step = plan.step_for(BUILDER)
        if builder_step is not None and builder_step.loot_prioritise == "elixir":
            if not self._confirm_bb_elixir_prioritise():
                return

        if plan.rotating and not self._confirm_rotation(plan):
            return

        self._controller.start(plan)

    # -- misc ----------------------------------------------------------------

    def is_star_bonus_enabled(self) -> bool:
        """True when any included village farms its star bonus (drives the status text)."""
        return any(self._panels[v].star_bonus() for v in self._included_villages())

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
