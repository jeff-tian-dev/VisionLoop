from __future__ import annotations

import logging
from typing import Any

import httpx

from .settings import get_settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def init_pool() -> None:
    global _client
    settings = get_settings()
    base = settings.supabase_url.rstrip("/") + "/rest/v1"
    _client = httpx.AsyncClient(
        base_url=base,
        headers={
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {settings.supabase_anon_key}",
        },
        timeout=httpx.Timeout(20.0),
    )
    logger.info("Supabase REST client ready → %s", base)


async def close_pool() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
        logger.info("Supabase REST client closed")


def _client_required() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Supabase REST client not initialized")
    return _client


async def ping() -> bool:
    try:
        r = await _client_required().get("/licenses", params={"select": "id", "limit": "1"})
        return r.status_code == 200
    except Exception as exc:
        logger.error("Supabase ping failed: %s", exc)
        return False


async def rpc_validate_license(
    *,
    license_key: str,
    machine_fingerprint: str,
    bot_version: str,
    client_ip: str,
) -> dict[str, Any]:
    """Call Postgres RPC `validate_license` exposed via PostgREST."""
    payload = {
        "p_license_key": license_key,
        "p_machine_fingerprint": machine_fingerprint,
        "p_bot_version": bot_version,
        "p_ip": client_ip,
    }
    r = await _client_required().post("/rpc/validate_license", json=payload)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected RPC payload: {data!r}")
    return data


async def rpc_trial_heartbeat(
    *,
    machine_fingerprint: str,
    elapsed_seconds: int,
    client_ip: str,
) -> dict[str, Any]:
    """Call Postgres RPC `trial_heartbeat` exposed via PostgREST.

    elapsed_seconds=0 is a read-only probe (no debit).
    Returns {ok, remaining_seconds, used_seconds} or {ok:false, reason, remaining_seconds:0}.
    """
    payload = {
        "p_machine_fingerprint": machine_fingerprint,
        "p_elapsed_seconds": elapsed_seconds,
        "p_ip": client_ip,
    }
    r = await _client_required().post("/rpc/trial_heartbeat", json=payload)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected RPC payload: {data!r}")
    return data


async def rpc_unpair_license(
    *,
    license_key: str,
    machine_fingerprint: str,
    bot_version: str,
    client_ip: str,
) -> dict[str, Any]:
    """Call Postgres RPC `unpair_license` exposed via PostgREST."""
    payload = {
        "p_license_key": license_key,
        "p_machine_fingerprint": machine_fingerprint,
        "p_bot_version": bot_version,
        "p_ip": client_ip,
    }
    r = await _client_required().post("/rpc/unpair_license", json=payload)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected RPC payload: {data!r}")
    return data


async def fetch_license_ids_by_session(stripe_checkout_session_id: str) -> list[str]:
    r = await _client_required().get(
        "/licenses",
        params={
            "select": "id",
            "stripe_checkout_session_id": f"eq.{stripe_checkout_session_id}",
            "limit": "1",
        },
    )
    r.raise_for_status()
    rows = r.json()
    return [row["id"] for row in rows] if isinstance(rows, list) else []


async def insert_license_row(
    *,
    license_key: str,
    email: str,
    stripe_customer_id: str | None,
    stripe_payment_intent: str | None,
    stripe_checkout_session_id: str,
    expires_at: str | None = None,
    stripe_subscription_id: str | None = None,
) -> bool:
    """Insert a license row. Returns True if a new row was created, False if duplicate session."""
    existing = await fetch_license_ids_by_session(stripe_checkout_session_id)
    if existing:
        return False

    body: dict[str, Any] = {
        "license_key": license_key,
        "status": "active",
        "email": email,
        "stripe_customer_id": stripe_customer_id,
        "stripe_payment_intent_id": stripe_payment_intent,
        "stripe_checkout_session_id": stripe_checkout_session_id,
    }
    if expires_at is not None:
        body["expires_at"] = expires_at
    if stripe_subscription_id is not None:
        body["stripe_subscription_id"] = stripe_subscription_id
    r = await _client_required().post("/licenses", json=body, headers={"Prefer": "return=minimal"})
    if r.status_code == 409:
        return False
    r.raise_for_status()
    return True


async def try_claim_stripe_fulfillment(*, stripe_checkout_session_id: str, variant: str) -> bool:
    """Insert idempotency row. Returns True if this request claimed processing (INSERT ok)."""
    body = {"stripe_checkout_session_id": stripe_checkout_session_id, "variant": variant}
    r = await _client_required().post(
        "/stripe_checkout_fulfillments",
        json=body,
        headers={"Prefer": "return=minimal"},
    )
    if r.status_code in (200, 201):
        return True
    if r.status_code == 409:
        return False
    r.raise_for_status()
    return True


async def fetch_license_by_key(license_key: str) -> dict[str, Any] | None:
    r = await _client_required().get(
        "/licenses",
        params={
            "license_key": f"eq.{license_key}",
            "select": "id,license_key,status,expires_at,email",
            "limit": "1",
        },
        headers={"Prefer": "return=representation"},
    )
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


async def patch_license_expires_at_by_key(
    *,
    license_key: str,
    expires_at: str,
    stripe_customer_id: str | None = None,
    stripe_payment_intent: str | None = None,
) -> int:
    """PATCH expiry (and optionally Stripe ids) by license_key. Returns row count."""
    body: dict[str, Any] = {"expires_at": expires_at}
    if stripe_customer_id is not None:
        body["stripe_customer_id"] = stripe_customer_id
    if stripe_payment_intent is not None:
        body["stripe_payment_intent_id"] = stripe_payment_intent
    r = await _client_required().patch(
        "/licenses",
        params={"license_key": f"eq.{license_key}"},
        json=body,
        headers={"Prefer": "return=representation"},
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return len(data)
    return 1 if data else 0


async def patch_license_by_subscription(
    *,
    stripe_subscription_id: str,
    expires_at: str,
    stripe_customer_id: str | None = None,
) -> int:
    """PATCH licenses by stripe_subscription_id. Returns number of rows returned (0 if none matched)."""
    body: dict[str, Any] = {"expires_at": expires_at}
    if stripe_customer_id is not None:
        body["stripe_customer_id"] = stripe_customer_id
    r = await _client_required().patch(
        "/licenses",
        params={"stripe_subscription_id": f"eq.{stripe_subscription_id}"},
        json=body,
        headers={"Prefer": "return=representation"},
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return len(data)
    return 1 if data else 0
