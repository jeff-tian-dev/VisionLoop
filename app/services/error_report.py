"""Fire-and-forget crash reporting to the license API server.

Only fatal bot crashes should call :func:`report_bot_crash`. Routine vision/log
noise is intentionally excluded.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Literal, Optional

import requests

from .license import HardwareFingerprint

logger = logging.getLogger(__name__)

_API_BASE = "https://clashautoloot.duckdns.org"
_REPORT_URL = f"{_API_BASE}/v1/report-error"

_REPORT_INTERVAL_S = 5 * 60
_MAX_MESSAGE_LEN = 2000
_MAX_TYPE_LEN = 200

# Redact Windows user paths from error text before upload.
_USER_PATH_RE = re.compile(
    r"(?i)([A-Z]:\\Users\\)[^\\]+(\\.*)?",
)

_last_report_mono = 0.0
_throttle_lock = threading.Lock()
_client: Optional[requests.Session] = None
_client_lock = threading.Lock()

LicenseMode = Literal["licensed", "trial"]


def _get_session() -> requests.Session:
    global _client
    with _client_lock:
        if _client is None:
            _client = requests.Session()
            _client.headers.update({"Content-Type": "application/json"})
        return _client


def _sanitize_message(message: str) -> str:
    text = message.strip().replace("\r\n", "\n").replace("\r", "\n")
    text = _USER_PATH_RE.sub(r"\1<user>\2", text)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "..."
    return text


def _sanitize_type(error_type: str) -> str:
    text = error_type.strip()
    if len(text) > _MAX_TYPE_LEN:
        text = text[:_MAX_TYPE_LEN]
    return text or "Exception"


def _should_send_report() -> bool:
    global _last_report_mono
    now = time.monotonic()
    with _throttle_lock:
        if now - _last_report_mono < _REPORT_INTERVAL_S:
            return False
        _last_report_mono = now
        return True


def report_bot_crash(
    error: BaseException,
    *,
    bot_version: str,
    license_mode: LicenseMode,
) -> None:
    """Queue a crash report. Never raises; silently no-ops when throttled."""
    if not _should_send_report():
        return

    message = _sanitize_message(str(error))
    if not message:
        return

    error_type = _sanitize_type(type(error).__name__)
    version = bot_version.strip() or "unknown"

    def worker() -> None:
        try:
            payload = {
                "machine_fingerprint": HardwareFingerprint.compute(),
                "license_mode": license_mode,
                "error_type": error_type,
                "error_message": message,
                "bot_version": version,
            }
            resp = _get_session().post(_REPORT_URL, json=payload, timeout=(3, 8))
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Crash report failed: %s", exc)
        except Exception as exc:
            logger.debug("Crash report unexpected error: %s", exc)

    threading.Thread(target=worker, daemon=True, name="ErrorReport").start()
