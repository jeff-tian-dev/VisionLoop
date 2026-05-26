"""Settings page — profile preferences."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from app.ui.qt.theme import SPACING
from app.ui.qt.widgets import Card, PageTitle, SectionTitle, neutral_button, primary_button
from app.utils.profile_settings_store import (
    EARTHQUAKE_METHOD_OPTIONS,
    ProfileSettings,
    load_profile_settings,
    save_profile_settings,
)


class SettingsPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])
        layout.addWidget(PageTitle("Settings"))

        card = Card()
        card.card_layout.addWidget(SectionTitle("Earthquake placement"))
        self._earthquake = QComboBox()
        self._earthquake.addItems(list(EARTHQUAKE_METHOD_OPTIONS))
        card.card_layout.addWidget(self._earthquake)

        btn_row = QHBoxLayout()
        self._btn_save = primary_button("Save", parent=card)
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_save)
        self._btn_reset = neutral_button("Reset", parent=card)
        self._btn_reset.clicked.connect(self._reload)
        btn_row.addWidget(self._btn_reset)
        btn_row.addStretch()
        card.card_layout.addLayout(btn_row)
        layout.addWidget(card)
        layout.addStretch()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._reload()

    def _reload(self) -> None:
        settings = load_profile_settings()
        idx = self._earthquake.findText(settings.earthquake_method)
        if idx >= 0:
            self._earthquake.setCurrentIndex(idx)

    def _on_save(self) -> None:
        save_profile_settings(
            ProfileSettings(earthquake_method=self._earthquake.currentText())
        )
        win = self.window()
        if isinstance(win, QMainWindow) and win.statusBar() is not None:
            win.statusBar().showMessage("Saved", 1500)
