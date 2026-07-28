"""Reusable Qt widgets for the AutoLoot UI."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QRectF, QSize, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.services.license import LicenseState
from app.ui.qt.theme import SPACING, TOKENS

DOT_COLORS = {
    LicenseState.VALID: TOKENS["success"],
    LicenseState.VALIDATING: TOKENS["warning"],
    LicenseState.RETRYING: TOKENS["warning"],
    LicenseState.INVALID: TOKENS["danger"],
    LicenseState.EMPTY: TOKENS["danger"],
    LicenseState.STALE: TOKENS["danger"],
    LicenseState.UNREACHABLE: TOKENS["danger"],
}


def format_license_expires_on_line(sub: str) -> str:
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


class Card(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self._layout.setSpacing(SPACING["sm"])

    @property
    def card_layout(self) -> QVBoxLayout:
        return self._layout


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")
        self.setAutoFillBackground(False)


class PageTitle(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("PageTitle")


class StatusDot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor(TOKENS["danger"])
        self.setFixedSize(14, 14)

    def set_color(self, hex_or_name: str) -> None:
        self._color = QColor(hex_or_name)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(2, 2, 10, 10))


class ToggleSwitch(QCheckBox):
    def __init__(
        self,
        text: str = "",
        *,
        parent: Optional[QWidget] = None,
        danger: bool = False,
        under_development: bool = False,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("ToggleSwitch")
        self._danger = danger
        self._under_development = under_development
        self.setFixedHeight(24)
        if under_development:
            self.setChecked(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track_w, track_h = 40, 22
        x0 = 0
        y0 = (self.height() - track_h) // 2
        if self._under_development:
            on_color = QColor("#3f3f46")
            off_color = QColor("#2d2d33")
            text_color = QColor("#4a5568")
        else:
            on_color = QColor(TOKENS["danger"] if self._danger else TOKENS["primary"])
            off_color = QColor("#3f3f46")
            text_color = QColor(TOKENS["danger"] if self._danger else TOKENS["text"])
        track_color = on_color if self.isChecked() and not self._under_development else off_color
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(x0, y0, track_w, track_h, track_h / 2, track_h / 2)
        knob_d = 18
        knob_x = x0 + track_w - knob_d - 2 if self.isChecked() and not self._under_development else x0 + 2
        knob_y = y0 + (track_h - knob_d) // 2
        painter.setBrush(QColor("#a0a0a8" if self._under_development else "#ffffff"))
        painter.drawEllipse(knob_x, knob_y, knob_d, knob_d)
        if self.text():
            painter.setPen(text_color)
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            text_rect = QRectF(track_w + 10, 0, self.width() - track_w - 10, self.height())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._under_development:
            from app.ui.qt.dialogs import show_under_development

            show_under_development(self.window())
            return
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        text_w = self.fontMetrics().horizontalAdvance(self.text()) + 8 if self.text() else 0
        return QSize(40 + text_w + 10, 24)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)


def _styled_button(text: str, role: str, parent: Optional[QWidget] = None) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setProperty("role", role)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    return btn


def primary_button(text: str, *, parent: Optional[QWidget] = None) -> QPushButton:
    return _styled_button(text, "primary", parent)


def danger_button(text: str, *, parent: Optional[QWidget] = None) -> QPushButton:
    return _styled_button(text, "danger", parent)


def neutral_button(text: str, *, parent: Optional[QWidget] = None) -> QPushButton:
    return _styled_button(text, "neutral", parent)


def chip_button(text: str, *, parent: Optional[QWidget] = None) -> QPushButton:
    return _styled_button(text, "chip", parent)


def segment_button(
    text: str, *, parent: Optional[QWidget] = None, under_development: bool = False
) -> QPushButton:
    btn = _styled_button(text, "segment", parent)
    if under_development:
        btn.setCheckable(False)
        btn.setProperty("underDevelopment", True)
    else:
        btn.setCheckable(True)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    btn.setMinimumWidth(int(btn.sizeHint().width() * 1.10))
    return btn


class StepperButton(QPushButton):
    """Compact up/down arrow for numeric steppers."""

    def __init__(self, *, up: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._up = up
        self.setProperty("role", "stepper")
        self.setFixedSize(22, 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.style().unpolish(self)
        self.style().polish(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self.isEnabled():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOKENS["text"]))
        cx = self.width() / 2
        cy = self.height() / 2
        if self._up:
            points = [
                QPointF(cx, cy - 3),
                QPointF(cx - 4, cy + 2),
                QPointF(cx + 4, cy + 2),
            ]
        else:
            points = [
                QPointF(cx, cy + 3),
                QPointF(cx - 4, cy - 2),
                QPointF(cx + 4, cy - 2),
            ]
        painter.drawPolygon(QPolygonF(points))


class VisibilityToggleButton(QPushButton):
    """Minimal line-art eye toggle for password fields."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "icon")
        self.setCheckable(True)
        self.setFixedSize(34, 34)
        self.setToolTip("Show password")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.style().unpolish(self)
        self.style().polish(self)
        self.toggled.connect(lambda _: self.update())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(TOKENS["text"])
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.width() / 2
        cy = self.height() / 2
        painter.drawEllipse(QRectF(cx - 9, cy - 6, 18, 12))

        if self.isChecked():
            painter.drawLine(int(cx - 8), int(cy + 6), int(cx + 8), int(cy - 6))
        else:
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 2.5, cy - 2.5, 5, 5))
