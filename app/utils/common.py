import os
import sys
from pathlib import Path

def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = Path(sys._MEIPASS) # type: ignore
    except Exception:
        # Dev mode: this file is at <root>/app/utils/common.py, so root is 3 levels up
        base_path = Path(__file__).resolve().parent.parent.parent

    return base_path / relative_path


def get_user_app_data_dir() -> Path:
    """Per-user writable data (Windows: LOCALAPPDATA\\ClashAutoLoot)."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "ClashAutoLoot"
    return Path.home() / ".local" / "share" / "ClashAutoLoot"


def get_autoloot_log_path() -> Path:
    """Path to the rotating ``autoloot.log`` (alongside saved license data)."""
    ensure_dir(get_user_app_data_dir())
    return get_user_app_data_dir() / "autoloot.log"


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
