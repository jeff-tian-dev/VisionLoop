"""Dark theme tokens and QSS for the PySide6 UI."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "bg": "#0e1116",
    "surface": "#181d28",
    "surface_hi": "#222837",
    "border": "#1a2030",
    "border_hi": "#2a3142",
    "text": "#e6edf3",
    "text_muted": "#8b97a8",
    "primary": "#0ea5e9",
    "primary_hov": "#0284c7",
    "danger": "#ef4444",
    "danger_hov": "#dc2626",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "neutral": "#3d4556",
    "neutral_hov": "#4d5566",
    "neutral_dark": "#2d3444",
    "neutral_dark_hov": "#3d4455",
}

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
RADIUS = 10
SIDEBAR_WIDTH = 180
WINDOW_DEFAULT = (880, 620)
WINDOW_MIN = (720, 520)

STYLESHEET = f"""
QWidget {{
    background-color: {TOKENS['bg']};
    color: {TOKENS['text']};
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}}
QLabel {{
    background-color: transparent;
    padding: 0;
    margin: 0;
}}
QFrame#Card {{
    background-color: {TOKENS['surface']};
    border: 1px solid {TOKENS['border']};
    border-radius: {RADIUS}px;
}}
QLabel#SectionTitle {{
    color: {TOKENS['text_muted']};
    font-weight: bold;
    font-size: 13px;
    background-color: transparent;
}}
QLabel#SectionTitle:disabled {{
    color: #4a5568;
}}
QLabel#DurationUnit:disabled {{
    color: #4a5568;
}}
QLabel#PageTitle {{
    font-size: 20px;
    font-weight: bold;
    color: {TOKENS['text']};
    background-color: transparent;
}}
QPushButton {{
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 28px;
}}
QPushButton[role="primary"] {{
    background-color: {TOKENS['primary']};
    color: #fff;
    font-weight: bold;
}}
QPushButton[role="primary"]:hover {{
    background-color: {TOKENS['primary_hov']};
}}
QPushButton[role="primary"]:disabled {{
    background-color: #1a3a4a;
    color: #4a5568;
}}
QPushButton[role="danger"] {{
    background-color: {TOKENS['danger']};
    color: #fff;
    font-weight: bold;
}}
QPushButton[role="danger"]:hover {{
    background-color: {TOKENS['danger_hov']};
}}
QPushButton[role="danger"]:disabled {{
    background-color: #3a1717;
    color: #4a5568;
}}
QPushButton[role="neutral"] {{
    background-color: {TOKENS['neutral']};
    color: {TOKENS['text']};
}}
QPushButton[role="neutral"]:hover {{
    background-color: {TOKENS['neutral_hov']};
}}
QPushButton[role="chip"] {{
    background-color: {TOKENS['neutral_dark']};
    color: {TOKENS['text']};
    padding: 4px 10px;
    min-height: 24px;
}}
QPushButton[role="chip"]:hover {{
    background-color: {TOKENS['neutral_dark_hov']};
}}
QPushButton[role="chip"]:disabled {{
    background-color: {TOKENS['surface_hi']};
    color: #4a5568;
}}
QPushButton[role="segment"] {{
    background-color: transparent;
    border: 1px solid {TOKENS['border_hi']};
    color: {TOKENS['text_muted']};
}}
QPushButton[role="segment"]:checked {{
    background-color: {TOKENS['primary']};
    color: #fff;
    border-color: {TOKENS['primary']};
    font-weight: bold;
}}
QPushButton[role="segment"][underDevelopment="true"] {{
    color: #4a5568;
    border-color: #3f3f46;
}}
QPushButton[role="segment"]:disabled {{
    color: #4a5568;
    border-color: #3f3f46;
}}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {TOKENS['surface_hi']};
    border: 1px solid {TOKENS['border_hi']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {TOKENS['primary']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {TOKENS['primary']};
}}
QSpinBox#DurationSpin {{
    min-height: 28px;
    max-height: 28px;
    padding: 2px 6px;
}}
QSpinBox:disabled, QSpinBox#DurationSpin:disabled {{
    color: #4a5568;
    background-color: {TOKENS['surface']};
    border-color: {TOKENS['border']};
}}
QPushButton[role="stepper"] {{
    background-color: {TOKENS['neutral_dark']};
    padding: 0;
    min-height: 13px;
    max-height: 13px;
    min-width: 22px;
    max-width: 22px;
    border-radius: 4px;
}}
QPushButton[role="stepper"]:hover {{
    background-color: {TOKENS['neutral_dark_hov']};
}}
QPushButton[role="stepper"]:pressed {{
    background-color: {TOKENS['neutral']};
}}
QPushButton[role="stepper"]:disabled {{
    background-color: {TOKENS['surface_hi']};
}}
QPushButton[role="help"] {{
    background-color: transparent;
    color: {TOKENS['text_muted']};
    padding: 0;
    min-height: 18px;
    min-width: 18px;
    max-height: 18px;
    max-width: 18px;
    border-radius: 9px;
    border: 1px solid {TOKENS['text_muted']};
    font-size: 11px;
    font-weight: bold;
}}
QPushButton[role="help"]:hover {{
    color: {TOKENS['text']};
    border-color: {TOKENS['text']};
}}
QPushButton[role="icon"] {{
    background-color: {TOKENS['neutral_dark']};
    color: {TOKENS['text']};
    padding: 0;
    min-height: 34px;
    min-width: 34px;
    max-height: 34px;
    max-width: 34px;
    border-radius: 6px;
}}
QPushButton[role="icon"]:hover {{
    background-color: {TOKENS['neutral_dark_hov']};
}}
QPushButton[role="icon"]:checked {{
    background-color: {TOKENS['neutral']};
}}
QListWidget#Sidebar {{
    background-color: #151a22;
    border: none;
    padding: 6px;
}}
QListWidget#Sidebar::item {{
    padding: 10px 14px;
    border-radius: 8px;
    color: {TOKENS['text_muted']};
}}
QListWidget#Sidebar::item:selected {{
    background-color: {TOKENS['primary']};
    color: #fff;
}}
QListWidget#Sidebar::item:hover:!selected {{
    background-color: {TOKENS['surface_hi']};
    color: {TOKENS['text']};
}}
QStatusBar {{
    background-color: {TOKENS['surface']};
    border-top: 1px solid {TOKENS['border']};
}}
QStatusBar::item {{
    border: none;
}}
QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {TOKENS['border_hi']};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}
QCheckBox#ToggleSwitch {{
    spacing: 8px;
    background-color: transparent;
}}
QCheckBox#ToggleSwitch::indicator {{
    width: 0;
    height: 0;
    border: none;
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(TOKENS["bg"]))
    pal.setColor(QPalette.Base, QColor(TOKENS["surface_hi"]))
    pal.setColor(QPalette.AlternateBase, QColor(TOKENS["surface"]))
    pal.setColor(QPalette.Text, QColor(TOKENS["text"]))
    pal.setColor(QPalette.WindowText, QColor(TOKENS["text"]))
    pal.setColor(QPalette.Button, QColor(TOKENS["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(TOKENS["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(TOKENS["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(TOKENS["text"]))
    pal.setColor(QPalette.Highlight, QColor(TOKENS["primary"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
