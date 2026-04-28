import os
import sys
from pathlib import Path
from typing import Tuple, Optional

# Type aliases
Point = Tuple[int, int]
Rect = Tuple[int, int, int, int]  # x, y, w, h

def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = Path(sys._MEIPASS) # type: ignore
    except Exception:
        # Dev mode: this file is at <root>/app/utils/common.py, so root is 3 levels up
        base_path = Path(__file__).resolve().parent.parent.parent

    return base_path / relative_path


def get_template_path(template_name: str) -> Path:
    """
    Return ``templates/<16_10|16_9>/…`` for the active aspect (see :class:`app.config.Config`).
    ``template_name`` should be a filename like ``attack.png`` (not a subpath with ``..``).
    """
    from app.config import Config  # local import: avoids circular import at app load

    sub = Config().aspect_key
    return get_resource_path(f"templates/{sub}/{template_name}")


def ensure_dir(path: Path) -> None:
    """Ensure a directory exists."""
    path.mkdir(parents=True, exist_ok=True)
