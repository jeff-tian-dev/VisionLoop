"""License key validation for Clash Auto Loot.

Components
----------
HardwareFingerprint  - Stable 32-hex machine ID (MachineGuid + board serial).
LicenseClient        - HTTP calls to the validation API.
LicenseState         - Enum of all possible client states.
LicenseManager       - State machine + background scheduler. Singleton.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import threading
import time
import winreg
from enum import Enum, auto
from pathlib import Path
from datetime import date, datetime
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# ─── Public API URL ───────────────────────────────────────────────────────────
_API_BASE = "https://clashautoloot.duckdns.org"
_VALIDATE_URL = f"{_API_BASE}/v1/validate"

# ─── Timing ───────────────────────────────────────────────────────────────────
_RECHECK_INTERVAL_S = 3 * 60 * 60      # 3 hours
_RETRY_INTERVAL_S = 30                  # retry every 30 s when unreachable
_RETRY_MAX_S = 15 * 60                  # give up after 15 min of retries

# ─── States ───────────────────────────────────────────────────────────────────

class LicenseState(Enum):
    EMPTY       = auto()   # field is empty / never activated
    VALIDATING  = auto()   # request in flight or about to be sent
    VALID       = auto()   # last check passed
    INVALID     = auto()   # server said key is bad (not_found / revoked / mismatch)
    STALE       = auto()   # user edited the field since last successful activation
    RETRYING    = auto()   # network error; retrying every 30 s for up to 15 min
    UNREACHABLE = auto()   # 15 min of retries exhausted


_REASON_MESSAGES: dict[str, str] = {
    "not_found": "License key is invalid.",
    "revoked": "This license key has been revoked.",
    "expired": "This subscription license has expired. Renew your subscription or purchase a lifetime key.",
    "machine_mismatch": "This license key is already activated on another machine.",
    "invalid_format": "License key format is invalid. Use the exact key from your email (CLASH-…, letters and digits only).",
    "network_unreachable": "Could not reach the license server. Please check your internet connection.",
    "empty": "Please enter a license key and click Check Key.",
}


# ─── Hardware fingerprint ─────────────────────────────────────────────────────

class HardwareFingerprint:
    _cache: Optional[str] = None

    @classmethod
    def compute(cls) -> str:
        if cls._cache is not None:
            return cls._cache
        cls._cache = cls._build()
        return cls._cache

    @classmethod
    def _build(cls) -> str:
        parts = [
            cls._machine_guid(),
            cls._motherboard_serial(),
        ]
        combined = "|".join(parts)
        digest = hashlib.sha256(combined.encode()).hexdigest()[:32]
        logger.debug("Hardware fingerprint computed (first 8: %s...)", digest[:8])
        return digest

    @staticmethod
    def _machine_guid() -> str:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            return str(value).strip()
        except Exception:
            return "<unavailable>"

    @staticmethod
    def _motherboard_serial() -> str:
        try:
            sub_kw: dict = {
                "timeout": 5,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                sub_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_BaseBoard).SerialNumber"],
                **sub_kw,
            )
            return result.decode(errors="ignore").strip()
        except Exception:
            return "<unavailable>"


# ─── HTTP client ──────────────────────────────────────────────────────────────

class LicenseClient:
    def __init__(self, api_base: str = _API_BASE) -> None:
        self._validate_url = f"{api_base}/v1/validate"
        self._unpair_url = f"{api_base}/v1/unpair"
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def validate(self, license_key: str, bot_version: str = "1.0.0") -> dict:
        """Call /v1/validate. Returns parsed JSON dict.

        Raises requests.RequestException on network error.
        """
        normalized_key = license_key.strip().upper()
        payload = {
            "license_key": normalized_key,
            "machine_fingerprint": HardwareFingerprint.compute(),
            "bot_version": bot_version,
        }
        resp = self._session.post(
            self._validate_url,
            json=payload,
            timeout=(5, 10),
        )
        resp.raise_for_status()
        return resp.json()

    def unpair(self, license_key: str, bot_version: str = "1.0.0") -> dict:
        """POST /v1/unpair. Returns {\"ok\": bool, optional \"reason\"}. Raises on HTTP/network."""
        normalized_key = license_key.strip().upper()
        payload = {
            "license_key": normalized_key,
            "machine_fingerprint": HardwareFingerprint.compute(),
            "bot_version": bot_version,
        }
        resp = self._session.post(
            self._unpair_url,
            json=payload,
            timeout=(5, 10),
        )
        resp.raise_for_status()
        return resp.json()


# ─── License persistence ──────────────────────────────────────────────────────

def _key_file() -> Path:
    from app.utils.common import ensure_dir, get_user_app_data_dir
    d = get_user_app_data_dir()
    ensure_dir(d)
    return d / "license.json"


def load_saved_key() -> str:
    try:
        data = json.loads(_key_file().read_text(encoding="utf-8"))
        return str(data.get("license_key", "")).strip().upper()
    except Exception:
        return ""


def clear_saved_key() -> None:
    try:
        path = _key_file()
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("Could not remove license file: %s", exc)


def save_key(key: str) -> None:
    try:
        normalized = key.strip().upper()
        _key_file().write_text(
            json.dumps({"license_key": normalized}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not save license key: %s", exc)


# ─── License Manager ─────────────────────────────────────────────────────────

StateCallback = Callable[[LicenseState, str], None]


class LicenseManager:
    """Singleton license state machine with background scheduler.

    Thread-safety: state transitions happen on a background daemon thread.
    UI callbacks are invoked from that thread; GUI code must marshal via
    ``app.after(0, ...)`` when updating widgets.
    """

    def __init__(self, bot_version: str = "1.0.0") -> None:
        self._client = LicenseClient()
        self._bot_version = bot_version
        self._lock = threading.Lock()

        self._state = LicenseState.EMPTY
        self._reason: str = "empty"
        self._license_key: str = ""
        self._expires_at_raw: Optional[object] = None  # ISO string from API, or None = lifetime

        # Retry tracking
        self._retry_start: float = 0.0

        # Background thread control
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._recheck_event = threading.Event()  # signal immediate recheck

        # UI callback — called whenever state changes; may be None
        self._on_state_change: Optional[StateCallback] = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> LicenseState:
        with self._lock:
            return self._state

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def user_message(self) -> str:
        return _REASON_MESSAGES.get(self.reason, "License key is invalid.")

    @property
    def license_expiry_subcaption(self) -> str:
        """UI line under 'Licensed.': 'Expires on: YYYY-MM-DD' or 'Never' (lifetime). Empty if not VALID."""
        with self._lock:
            if self._state != LicenseState.VALID:
                return ""
            raw = self._expires_at_raw
        if raw is None:
            return "Never"
        s = str(raw).strip()
        if not s:
            return "Never"
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            d: date
            if len(s) >= 10 and s[4] == "-" and s[7] == "-" and "T" not in s[:10]:
                d = date.fromisoformat(s[:10])
            else:
                d = datetime.fromisoformat(s).date()
            return f"Expires on: {d.isoformat()}"
        except Exception:
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return f"Expires on: {s[:10]}"
            return "Never"

    def set_on_state_change(self, callback: StateCallback) -> None:
        self._on_state_change = callback

    def start(self, license_key: str) -> None:
        """Load a key and start the background scheduler.

        Triggers an immediate validation in the background thread.
        """
        notify_empty = False
        with self._lock:
            self._license_key = license_key.strip().upper()
            if not self._license_key:
                self._apply_state_locked(LicenseState.EMPTY, "empty")
                notify_empty = True
            else:
                self._state = LicenseState.VALIDATING
                self._reason = ""

        if notify_empty:
            self._notify_state_change(LicenseState.EMPTY, "empty")

        if self._scheduler_thread is None or not self._scheduler_thread.is_alive():
            self._stop_event.clear()
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name="LicenseScheduler",
            )
            self._scheduler_thread.start()
        else:
            # Signal existing thread to recheck now
            self._recheck_event.set()

    def recheck(self, new_key: Optional[str] = None) -> None:
        """Trigger an immediate re-validation from the UI thread.

        If ``new_key`` is provided, updates working key only; ``license.json`` is written
        after the server confirms ``valid`` (see ``_do_validate``). Empty key clears disk.
        """
        if new_key is not None:
            stripped = new_key.strip().upper()
            if not stripped:
                clear_saved_key()
                with self._lock:
                    self._license_key = ""
                    self._apply_state_locked(LicenseState.EMPTY, "empty")
                self._notify_state_change(LicenseState.EMPTY, "empty")
                self._recheck_event.set()
                if self._scheduler_thread is None or not self._scheduler_thread.is_alive():
                    self.start("")
                return
            with self._lock:
                self._license_key = stripped
                self._state = LicenseState.VALIDATING
                self._reason = ""

        self._recheck_event.set()
        if self._scheduler_thread is None or not self._scheduler_thread.is_alive():
            self.start(self._license_key)

    def stop(self) -> None:
        self._stop_event.set()
        self._recheck_event.set()  # unblock wait

    def mark_stale(self) -> None:
        """Called when user edits the key field; dot goes red until Check Key validates."""
        notify: Optional[tuple[LicenseState, str]] = None
        with self._lock:
            if self._state == LicenseState.VALID:
                self._apply_state_locked(LicenseState.STALE, "stale")
                notify = (LicenseState.STALE, "stale")
        if notify:
            self._notify_state_change(*notify)

    def try_unpair(self, license_key: str) -> tuple[bool, str]:
        """Remove this machine's hardware bind on the server. Returns (success, reason_code_or_empty)."""
        stripped = license_key.strip().upper()
        if not stripped:
            return False, "empty"
        try:
            out = self._client.unpair(stripped, self._bot_version)
        except requests.RequestException as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code == 422:
                return False, "invalid_format"
            logger.warning("License unpair request failed: %s", exc)
            return False, "network_unreachable"

        if bool(out.get("ok")):
            return True, ""
        return False, str(out.get("reason", "failed"))

    # ── Internal ─────────────────────────────────────────────────────────────

    def _apply_state_locked(
        self,
        state: LicenseState,
        reason: str,
        *,
        expires_at: Optional[object] = None,
    ) -> None:
        """Mutate state only. Caller must hold :attr:`_lock`; do not call UI from here."""
        self._state = state
        self._reason = reason
        if state == LicenseState.VALID:
            self._expires_at_raw = expires_at
        elif state != LicenseState.STALE:
            self._expires_at_raw = None

    def _notify_state_change(self, state: LicenseState, reason: str) -> None:
        """Invoke UI callback **without** holding :attr:`_lock` (avoids Tk/main-thread deadlock)."""
        cb = self._on_state_change
        if not cb:
            return
        try:
            cb(state, reason)
        except Exception:
            pass

    def _do_validate(self) -> None:
        with self._lock:
            key = self._license_key

        if not key:
            with self._lock:
                self._apply_state_locked(LicenseState.EMPTY, "empty")
            self._notify_state_change(LicenseState.EMPTY, "empty")
            return

        with self._lock:
            self._state = LicenseState.VALIDATING
        if self._on_state_change:
            try:
                self._on_state_change(LicenseState.VALIDATING, "")
            except Exception:
                pass

        try:
            result = self._client.validate(key, self._bot_version)
            self._retry_start = 0.0  # reset retry clock on any successful network call

            if result.get("valid"):
                with self._lock:
                    persisted = self._license_key.strip().upper()
                    self._apply_state_locked(
                        LicenseState.VALID,
                        "ok",
                        expires_at=result.get("expires_at"),
                    )
                save_key(persisted)
                self._notify_state_change(LicenseState.VALID, "ok")
            else:
                reason = result.get("reason", "invalid")
                with self._lock:
                    self._apply_state_locked(LicenseState.INVALID, reason)
                self._notify_state_change(LicenseState.INVALID, reason)

        except requests.RequestException as exc:
            if (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and exc.response.status_code == 422
            ):
                logger.warning(
                    "License validation rejected (422): %s",
                    (exc.response.text or "")[:400],
                )
                with self._lock:
                    self._apply_state_locked(LicenseState.INVALID, "invalid_format")
                self._notify_state_change(LicenseState.INVALID, "invalid_format")
                return

            logger.warning("License validation network error: %s", exc)
            now = time.monotonic()
            if self._retry_start == 0.0:
                self._retry_start = now

            elapsed = now - self._retry_start
            if elapsed >= _RETRY_MAX_S:
                with self._lock:
                    self._apply_state_locked(
                        LicenseState.UNREACHABLE, "network_unreachable"
                    )
                self._notify_state_change(
                    LicenseState.UNREACHABLE, "network_unreachable"
                )
            else:
                with self._lock:
                    self._apply_state_locked(LicenseState.RETRYING, "network_retrying")
                self._notify_state_change(LicenseState.RETRYING, "network_retrying")

    def _scheduler_loop(self) -> None:
        # Initial check immediately
        self._do_validate()

        while not self._stop_event.is_set():
            state = self.state

            if state == LicenseState.RETRYING:
                wait = _RETRY_INTERVAL_S
            else:
                wait = _RECHECK_INTERVAL_S
                self._retry_start = 0.0

            # Wait, but wake up early if recheck_event is set
            self._recheck_event.wait(timeout=wait)
            self._recheck_event.clear()

            if self._stop_event.is_set():
                break

            current_state = self.state
            if current_state == LicenseState.STALE:
                # User edited the field — don't auto-recheck, wait for manual click
                continue

            self._do_validate()