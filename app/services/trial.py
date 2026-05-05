"""Trial runtime wallet for Clash Auto Loot.

Calls POST /v1/trial/heartbeat on the license API server.
elapsed_seconds=0 is a read-only probe (no debit).
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from .license import HardwareFingerprint

logger = logging.getLogger(__name__)

_API_BASE = "https://clashautoloot.duckdns.org"
_HEARTBEAT_URL = f"{_API_BASE}/v1/trial/heartbeat"

TRIAL_TOTAL_SECONDS: int = 3600
TRIAL_HEARTBEAT_INTERVAL_MS: int = 60_000
_LOCAL_ELAPSED_CAP: int = 125  # sanity cap before sending to server


class TrialResult:
    __slots__ = ("ok", "remaining_seconds", "used_seconds", "reason")

    def __init__(
        self,
        ok: bool,
        remaining_seconds: int,
        used_seconds: int = 0,
        reason: str = "",
    ) -> None:
        self.ok = ok
        self.remaining_seconds = remaining_seconds
        self.used_seconds = used_seconds
        self.reason = reason

    @property
    def allowed(self) -> bool:
        return self.ok and self.remaining_seconds > 0


class TrialClient:
    def __init__(self, api_base: str = _API_BASE) -> None:
        self._url = f"{api_base}/v1/trial/heartbeat"
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def heartbeat(self, elapsed_seconds: int = 0, bot_version: str = "1.0.0") -> TrialResult:
        """POST /v1/trial/heartbeat. elapsed_seconds=0 is a no-debit probe.

        Raises requests.RequestException on network error (caller decides policy).
        """
        fp = HardwareFingerprint.compute()
        capped = min(max(elapsed_seconds, 0), _LOCAL_ELAPSED_CAP)
        payload = {
            "machine_fingerprint": fp,
            "elapsed_seconds": capped,
            "bot_version": bot_version,
        }
        resp = self._session.post(self._url, json=payload, timeout=(5, 10))
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected trial heartbeat payload: {data!r}")
        return TrialResult(
            ok=bool(data.get("ok", False)),
            remaining_seconds=int(data.get("remaining_seconds", 0)),
            used_seconds=int(data.get("used_seconds", 0)),
            reason=str(data.get("reason", "")),
        )


# Module-level singleton so GUI imports are clean.
_client: Optional[TrialClient] = None


def get_trial_client() -> TrialClient:
    global _client
    if _client is None:
        _client = TrialClient()
    return _client


def fetch_trial_status(bot_version: str = "1.0.0") -> TrialResult:
    """Read-only probe: returns remaining without debiting. Never raises — returns
    a result with ok=False on any network/server error so callers can gate safely."""
    try:
        return get_trial_client().heartbeat(elapsed_seconds=0, bot_version=bot_version)
    except requests.RequestException as exc:
        logger.warning("Trial status fetch failed: %s", exc)
        return TrialResult(ok=False, remaining_seconds=0, reason="network_error")
    except Exception as exc:
        logger.warning("Trial status unexpected error: %s", exc)
        return TrialResult(ok=False, remaining_seconds=0, reason="error")


def send_trial_heartbeat(elapsed_seconds: int, bot_version: str = "1.0.0") -> TrialResult:
    """Debit elapsed_seconds and return updated remaining. Never raises."""
    try:
        return get_trial_client().heartbeat(elapsed_seconds=elapsed_seconds, bot_version=bot_version)
    except requests.RequestException as exc:
        logger.warning("Trial heartbeat failed: %s", exc)
        return TrialResult(ok=False, remaining_seconds=0, reason="network_error")
    except Exception as exc:
        logger.warning("Trial heartbeat unexpected error: %s", exc)
        return TrialResult(ok=False, remaining_seconds=0, reason="error")
