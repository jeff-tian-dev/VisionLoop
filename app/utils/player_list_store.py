"""Persist multi-run player list (JSON)."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List


@dataclass
class PlayerEntry:
    name: str
    enabled: bool = True


def get_player_list_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "player_list.json"
    return Path(__file__).resolve().parent.parent.parent / "player_list.json"


def load_players() -> List[PlayerEntry]:
    path = get_player_list_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    out: List[PlayerEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name or not isinstance(name, str):
            continue
        enabled = bool(item.get("enabled", True))
        out.append(PlayerEntry(name=name.strip(), enabled=enabled))
    return out


def save_players(players: List[PlayerEntry]) -> None:
    path = get_player_list_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: List[dict[str, Any]] = [asdict(p) for p in players]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
