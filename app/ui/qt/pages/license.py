"""License page — key entry, validation, checkout links."""

from __future__ import annotations

import webbrowser
from typing import Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.license import LicenseState, load_saved_key
from app.ui.qt._constants import MONTH_EXTEND_CHECKOUT_URL, STRIPE_LIFETIME_URL
from app.ui.qt.bot_controller import BotController
from app.ui.qt.dialogs import UnpairConfirmDialog, show_error
from app.ui.qt.theme import SPACING, TOKENS
from app.ui.qt.widgets import (
    DOT_COLORS,
    PageTitle,
    StatusDot,
    VisibilityToggleButton,
    primary_button,
    neutral_button,
)


class LicensePage(QWidget):
    _DEBOUNCE_MS = 200

    def __init__(self, controller: BotController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._show_plain = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(self._DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._refresh_status_caption)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])
        layout.addWidget(PageTitle("License"))

        intro = QLabel(
            "Edit your license key below. Nothing is saved or sent until you "
            "press Check Key — then the saved key file updates only if the "
            "server accepts it."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TOKENS['text_muted']};")
        layout.addWidget(intro)

        self._status_text = QTextEdit()
        self._status_text.setReadOnly(True)
        self._status_text.setFixedHeight(120)
        layout.addWidget(self._status_text)

        key_row = QHBoxLayout()
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("CLASH-XXXX-XXXX-XXXX-XXXX")
        self._entry.setEchoMode(QLineEdit.Password)
        mono = QFont("Courier New", 10)
        self._entry.setFont(mono)
        self._entry.textEdited.connect(self._on_key_typed)
        key_row.addWidget(self._entry, stretch=1)

        self._eye_btn = VisibilityToggleButton(parent=self)
        self._eye_btn.toggled.connect(self._on_visibility_toggled)
        key_row.addWidget(self._eye_btn)

        self._dot = StatusDot()
        key_row.addWidget(self._dot)

        self._btn_check = primary_button("Check Key", parent=self)
        self._btn_check.clicked.connect(self._on_check_key)
        key_row.addWidget(self._btn_check)
        layout.addLayout(key_row)

        footer = QHBoxLayout()
        self._btn_monthly = primary_button("Buy / extend subscription", parent=self)
        self._btn_monthly.clicked.connect(self._open_monthly_checkout)
        footer.addWidget(self._btn_monthly)
        self._btn_lifetime = neutral_button("Buy lifetime", parent=self)
        self._btn_lifetime.clicked.connect(self._open_lifetime_checkout)
        footer.addWidget(self._btn_lifetime)
        self._btn_unpair = neutral_button("Unpair…", parent=self)
        self._btn_unpair.clicked.connect(self._open_unpair)
        footer.addWidget(self._btn_unpair)
        footer.addStretch()
        layout.addLayout(footer)
        layout.addStretch()

        self._controller.licenseChanged.connect(self._on_license_changed)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        saved = load_saved_key()
        self._entry.setText(saved)
        self._show_plain = False
        self._eye_btn.setChecked(False)
        self._entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._debounce_timer.stop()
        self._sync_from_controller()

    def hideEvent(self, event) -> None:  # noqa: N802
        saved = load_saved_key().strip().upper()
        typed = self._entry.text().strip().upper()
        if self._controller.license_state() == LicenseState.STALE or typed != saved:
            self._controller.recheck_license(new_key=saved)
            self._entry.setText(saved)
        super().hideEvent(event)

    def _on_license_changed(self, state: LicenseState, reason: str) -> None:
        self._sync_activate_buttons(state)
        if reason != "stale":
            self._sync_from_controller()
        self._paint_dot(state)

    def _sync_from_controller(self) -> None:
        state = self._controller.license_state()
        self._paint_dot(state)
        self._refresh_status_caption()
        self._sync_activate_buttons(state)

    def _sync_activate_buttons(self, state: LicenseState) -> None:
        self._btn_check.setEnabled(True)
        self._btn_check.setText("Check Key")
        if state in (LicenseState.VALIDATING, LicenseState.RETRYING):
            self._btn_check.setEnabled(False)

    def _paint_dot(self, state: LicenseState) -> None:
        self._dot.set_color(DOT_COLORS.get(state, TOKENS["danger"]))

    def _status_caption(self, state: LicenseState) -> Tuple[str, str]:
        if state == LicenseState.VALID:
            return ("Licensed.", TOKENS["success"])
        if state == LicenseState.VALIDATING:
            return ("Checking license…", TOKENS["warning"])
        if state == LicenseState.RETRYING:
            return ("Reconnecting to license server…", TOKENS["warning"])
        if state == LicenseState.STALE:
            return (
                "You edited the key since it was last validated. Click Check Key below to verify.",
                TOKENS["text_muted"],
            )
        if state == LicenseState.EMPTY:
            return (
                "No license yet. Paste your key below, then Check Key.",
                TOKENS["text_muted"],
            )
        if state in (LicenseState.INVALID, LicenseState.UNREACHABLE):
            return (self._controller.license_user_message(), TOKENS["danger"])
        return ("Unknown license status.", TOKENS["text_muted"])

    def _refresh_status_caption(self) -> None:
        text, color = self._status_caption(self._controller.license_state())
        self._status_text.setPlainText(text.rstrip() or " ")
        self._status_text.setStyleSheet(f"color: {color};")

    def _on_key_typed(self, _text: str) -> None:
        if self._controller.license_state() == LicenseState.VALID:
            self._controller.mark_license_stale()
        self._debounce_timer.stop()
        self._debounce_timer.start()

    def _on_check_key(self) -> None:
        self._debounce_timer.stop()
        key = self._entry.text().strip()
        self._btn_check.setEnabled(False)
        self._refresh_status_caption_for_state(LicenseState.VALIDATING)
        self._controller.recheck_license(new_key=key)

    def _refresh_status_caption_for_state(self, state: LicenseState) -> None:
        text, color = self._status_caption(state)
        self._status_text.setPlainText(text.rstrip() or " ")
        self._status_text.setStyleSheet(f"color: {color};")
        self._paint_dot(state)

    def _on_visibility_toggled(self, visible: bool) -> None:
        self._show_plain = visible
        self._entry.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self._eye_btn.setToolTip("Hide password" if visible else "Show password")

    def _open_lifetime_checkout(self) -> None:
        url = (STRIPE_LIFETIME_URL or "").strip()
        if not url:
            QMessageBox.information(
                self.window(),
                "Lifetime license",
                "The lifetime checkout URL is not set in this build yet.\n\n"
                "Contact support to purchase.",
            )
            return
        webbrowser.open(url)

    def _open_monthly_checkout(self) -> None:
        url = (MONTH_EXTEND_CHECKOUT_URL or "").strip()
        if not url:
            QMessageBox.information(
                self.window(),
                "Monthly access",
                "The monthly checkout URL is not set in this build yet.\n\n"
                "Try Buy lifetime, or contact support.",
            )
            return
        webbrowser.open(url)

    def _open_unpair(self) -> None:
        key = self._entry.text().strip()
        if not key:
            show_error(self.window(), "Unpair", "Enter your license key in the field above first.")
            return
        dlg = UnpairConfirmDialog(self.window(), self._controller, key)
        if dlg.exec():
            self._entry.clear()
            self._sync_from_controller()
