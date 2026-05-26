"""App logo and window icon."""

from __future__ import annotations

from PySide6.QtGui import QIcon, QPixmap

from app.utils.common import get_resource_path

_ICON: QIcon | None = None

LOGO_PNG = "assets/clash_autoloot_logo.png"
LOGO_ICO = "assets/clash_autoloot_logo.ico"


def app_icon() -> QIcon:
    """Return the cached application icon (ICO preferred on Windows)."""
    global _ICON
    if _ICON is None:
        ico = get_resource_path(LOGO_ICO)
        png = get_resource_path(LOGO_PNG)
        if ico.is_file():
            _ICON = QIcon(str(ico))
        elif png.is_file():
            _ICON = QIcon(str(png))
        else:
            _ICON = QIcon()
    return _ICON


def logo_pixmap(size: int = 48) -> QPixmap:
    """Square logo pixmap for in-app branding (sidebar header, etc.)."""
    icon = app_icon()
    if icon.isNull():
        return QPixmap()
    return icon.pixmap(size, size)


def apply_app_icon(widget) -> None:
    """Set the app logo on any QWidget with a title bar (QApplication, QMainWindow, QDialog)."""
    icon = app_icon()
    if not icon.isNull():
        widget.setWindowIcon(icon)
