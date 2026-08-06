from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Any

import httpx
import stripe
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import __version__
from .db import (
    close_pool,
    fetch_bound_fingerprint,
    fetch_license_billing_by_key,
    init_pool,
    patch_license_stripe_customer_by_key,
    ping,
    rpc_report_client_error,
    rpc_trial_heartbeat,
    rpc_unpair_license,
    rpc_validate_license,
)
from .fingerprint import is_valid_fingerprint
from .keys import LICENSE_KEY_RE
from .settings import get_settings
from .stripe_webhook import process_webhook

logger = logging.getLogger(__name__)

# ─── Rate limiter ─────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    await init_pool()
    yield
    await close_pool()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Clash Auto Loot License API", version=__version__, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ─── Models ───────────────────────────────────────────────────────────────────


class ValidateRequest(BaseModel):
    license_key: str
    machine_fingerprint: str
    bot_version: str = "unknown"

    @field_validator("license_key")
    @classmethod
    def validate_key_format(cls, v: str) -> str:
        if not re.match(LICENSE_KEY_RE, v):
            raise ValueError("Invalid license key format")
        return v

    @field_validator("machine_fingerprint")
    @classmethod
    def validate_fingerprint(cls, v: str) -> str:
        if not is_valid_fingerprint(v):
            raise ValueError("Invalid machine fingerprint format")
        return v


class UnpairRequest(ValidateRequest):
    """Same payload as validate; verifies this PC is the bound machine before deleting the bind."""


class PortalRequest(ValidateRequest):
    """Same payload as validate; opens the Stripe customer portal for the key's customer."""


class ReportErrorRequest(BaseModel):
    machine_fingerprint: str
    license_mode: str
    error_type: str = "Exception"
    error_message: str
    bot_version: str = "unknown"

    @field_validator("machine_fingerprint")
    @classmethod
    def validate_fingerprint(cls, v: str) -> str:
        if not is_valid_fingerprint(v):
            raise ValueError("Invalid machine fingerprint format")
        return v

    @field_validator("license_mode")
    @classmethod
    def validate_license_mode(cls, v: str) -> str:
        mode = v.strip().lower()
        if mode not in ("licensed", "trial"):
            raise ValueError("license_mode must be licensed or trial")
        return mode

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, v: str) -> str:
        text = v.strip() or "Exception"
        return text[:200]

    @field_validator("error_message")
    @classmethod
    def validate_error_message(cls, v: str) -> str:
        text = v.strip()
        if not text:
            raise ValueError("error_message must not be empty")
        return text[:2000]

    @field_validator("bot_version")
    @classmethod
    def validate_bot_version(cls, v: str) -> str:
        return (v.strip() or "unknown")[:64]


class TrialHeartbeatRequest(BaseModel):
    machine_fingerprint: str
    elapsed_seconds: int = 0
    bot_version: str = "unknown"

    @field_validator("machine_fingerprint")
    @classmethod
    def validate_fingerprint(cls, v: str) -> str:
        if not is_valid_fingerprint(v):
            raise ValueError("Invalid machine fingerprint format")
        return v

    @field_validator("elapsed_seconds")
    @classmethod
    def validate_elapsed(cls, v: int) -> int:
        if v < 0:
            raise ValueError("elapsed_seconds must be >= 0")
        return v


# ─── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/v1/health")
async def health() -> dict:
    db_ok = await ping()
    return {
        "status": "ok",
        "db": "ok" if db_ok else "error",
        "version": __version__,
    }


@app.get("/v1/checkout/month-extend")
@limiter.limit("10/minute")
async def checkout_month_extend(request: Request) -> RedirectResponse:
    """Create a server-side Stripe Checkout Session (one-time × months) and redirect the browser."""
    settings = get_settings()
    price_id = settings.month_extend_price_id()
    if not price_id:
        raise HTTPException(status_code=503, detail="month_extend_price_not_configured")

    def create_session():
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                    "adjustable_quantity": {"enabled": True, "minimum": 1, "maximum": 36},
                }
            ],
            custom_fields=[
                {
                    "key": "existing_license_key",
                    "label": {
                        "type": "custom",
                        "custom": "Existing license key (leave blank for a new key)",
                    },
                    "type": "text",
                    "optional": True,
                },
            ],
            success_url="https://clashautoloot.duckdns.org/?paid=extend",
            cancel_url="https://clashautoloot.duckdns.org/?cancel=extend",
            allow_promotion_codes=True,
        )

    try:
        session = await asyncio.to_thread(create_session)
    except stripe.StripeError as exc:
        logger.exception("Stripe Session.create(month-extend) failed: %s", exc)
        raise HTTPException(status_code=502, detail="stripe_error")

    url = getattr(session, "url", None) or (
        session.get("url") if isinstance(session, dict) else None
    )
    if not url:
        logger.error("Checkout session missing url (month-extend)")
        raise HTTPException(status_code=502, detail="missing_checkout_url")

    return RedirectResponse(url=url, status_code=302)


@app.get("/v1/checkout/subscribe")
@limiter.limit("10/minute")
async def checkout_subscribe(request: Request) -> RedirectResponse:
    """Create a Stripe Checkout Session for a monthly recurring subscription and redirect."""
    settings = get_settings()
    price_id = (settings.stripe_subscription_price_id or "").strip()
    if not price_id:
        raise HTTPException(status_code=503, detail="subscription_price_not_configured")

    def create_session():
        return stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://clashautoloot.duckdns.org/?paid=subscribe",
            cancel_url="https://clashautoloot.duckdns.org/?cancel=subscribe",
            allow_promotion_codes=True,
        )

    try:
        session = await asyncio.to_thread(create_session)
    except stripe.StripeError as exc:
        logger.exception("Stripe Session.create(subscribe) failed: %s", exc)
        raise HTTPException(status_code=502, detail="stripe_error")

    url = getattr(session, "url", None) or (
        session.get("url") if isinstance(session, dict) else None
    )
    if not url:
        logger.error("Checkout session missing url (subscribe)")
        raise HTTPException(status_code=502, detail="missing_checkout_url")

    return RedirectResponse(url=url, status_code=302)


@app.get("/v1/checkout/lifetime")
@limiter.limit("10/minute")
async def checkout_lifetime(request: Request) -> RedirectResponse:
    """Create a server-side Checkout Session for the configured lifetime price (STRIPE_PRICE_ID) and redirect."""
    settings = get_settings()
    price_id = (settings.stripe_price_id or "").strip()
    if not price_id:
        raise HTTPException(status_code=503, detail="lifetime_price_not_configured")

    def create_session():
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://clashautoloot.duckdns.org/?paid=lifetime",
            cancel_url="https://clashautoloot.duckdns.org/?cancel=lifetime",
            allow_promotion_codes=True,
        )

    try:
        session = await asyncio.to_thread(create_session)
    except stripe.StripeError as exc:
        logger.exception("Stripe Session.create(lifetime) failed: %s", exc)
        raise HTTPException(status_code=502, detail="stripe_error")

    url = getattr(session, "url", None) or (
        session.get("url") if isinstance(session, dict) else None
    )
    if not url:
        logger.error("Checkout session missing url (lifetime)")
        raise HTTPException(status_code=502, detail="missing_checkout_url")

    return RedirectResponse(url=url, status_code=302)


def _find_stripe_customer_by_email(email: str) -> str | None:
    """Legacy/comp keys may have no stripe_customer_id — fall back to an email match."""
    result = stripe.Customer.list(email=email, limit=1)
    data = getattr(result, "data", None) or []
    for cust in data:
        cid = cust.get("id") if isinstance(cust, dict) else getattr(cust, "id", None)
        deleted = cust.get("deleted") if isinstance(cust, dict) else getattr(cust, "deleted", None)
        if cid and not deleted:
            return str(cid)
    return None


@app.post("/v1/portal")
@limiter.limit("10/minute")
async def billing_portal(request: Request, body: PortalRequest) -> dict:
    """Create a Stripe Billing (customer) portal session for the license holder.

    Auth is the license key plus the bound machine fingerprint — the same secret the
    desktop app already holds. Expired keys are allowed through on purpose: renewing
    is exactly why someone opens the portal.
    """
    settings = get_settings()
    license_key = body.license_key.upper().strip()

    try:
        row = await fetch_license_billing_by_key(license_key)
    except Exception as exc:
        logger.exception("portal license lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail="license_backend_error")

    if not row:
        return {"ok": False, "reason": "not_found"}
    if row.get("status") == "revoked":
        return {"ok": False, "reason": "revoked"}

    try:
        bound = await fetch_bound_fingerprint(str(row["id"]))
    except Exception as exc:
        logger.exception("portal machine lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail="license_backend_error")

    if bound and bound != body.machine_fingerprint:
        return {"ok": False, "reason": "machine_mismatch"}

    customer_id = str(row.get("stripe_customer_id") or "").strip()
    email = str(row.get("email") or "").strip()

    if not customer_id and email:
        try:
            customer_id = await asyncio.to_thread(_find_stripe_customer_by_email, email) or ""
        except stripe.StripeError as exc:
            logger.exception("Stripe Customer.list failed for portal: %s", exc)
            raise HTTPException(status_code=502, detail="stripe_error")
        if customer_id:
            try:
                await patch_license_stripe_customer_by_key(
                    license_key=license_key, stripe_customer_id=customer_id
                )
            except Exception as exc:
                logger.warning("Could not backfill stripe_customer_id for portal: %s", exc)

    if not customer_id:
        logger.info("portal request for %s has no Stripe customer", license_key[:12])
        return {"ok": False, "reason": "no_billing_account"}

    def create_session():
        kwargs: dict[str, Any] = {
            "customer": customer_id,
            "return_url": settings.stripe_portal_return_url,
        }
        configuration = (settings.stripe_portal_configuration_id or "").strip()
        if configuration:
            kwargs["configuration"] = configuration
        return stripe.billing_portal.Session.create(**kwargs)

    try:
        session = await asyncio.to_thread(create_session)
    except stripe.InvalidRequestError as exc:
        message = str(getattr(exc, "user_message", "") or exc)
        if "configuration" in message.lower():
            logger.error("Stripe customer portal is not configured: %s", message)
            return {"ok": False, "reason": "portal_not_configured"}
        logger.exception("billing_portal.Session.create failed: %s", exc)
        raise HTTPException(status_code=502, detail="stripe_error")
    except stripe.StripeError as exc:
        logger.exception("billing_portal.Session.create failed: %s", exc)
        raise HTTPException(status_code=502, detail="stripe_error")

    url = getattr(session, "url", None) or (
        session.get("url") if isinstance(session, dict) else None
    )
    if not url:
        logger.error("Portal session missing url for customer %s", customer_id)
        raise HTTPException(status_code=502, detail="missing_portal_url")

    return {"ok": True, "url": url}


@app.post("/v1/validate")
@limiter.limit("30/minute")
async def validate(request: Request, body: ValidateRequest) -> dict:
    client_ip = get_remote_address(request)

    try:
        result = await rpc_validate_license(
            license_key=body.license_key,
            machine_fingerprint=body.machine_fingerprint,
            bot_version=body.bot_version,
            client_ip=client_ip,
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "validate_license RPC HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(status_code=502, detail="license_backend_error")
    except Exception as exc:
        logger.exception("validate_license RPC failed: %s", exc)
        raise HTTPException(status_code=502, detail="license_backend_error")

    valid = bool(result.get("valid"))
    out: dict = {"valid": valid}
    reason = result.get("reason")
    if reason:
        out["reason"] = reason
    if valid:
        # null = lifetime; ISO timestamp = subscription / timed key (migration 0006+)
        out["expires_at"] = result.get("expires_at")
    return out


@app.post("/v1/unpair")
@limiter.limit("20/minute")
async def unpair(request: Request, body: UnpairRequest) -> dict:
    client_ip = get_remote_address(request)

    try:
        result = await rpc_unpair_license(
            license_key=body.license_key.upper().strip(),
            machine_fingerprint=body.machine_fingerprint,
            bot_version=body.bot_version,
            client_ip=client_ip,
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "unpair_license RPC HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(status_code=502, detail="license_backend_error")
    except Exception as exc:
        logger.exception("unpair_license RPC failed: %s", exc)
        raise HTTPException(status_code=502, detail="license_backend_error")

    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason", "failed")}
    out: dict[str, Any] = {"ok": True}
    if result.get("reason"):
        out["reason"] = result["reason"]
    return out


@app.post("/v1/report-error")
@limiter.limit("30/minute")
async def report_error(request: Request, body: ReportErrorRequest) -> dict:
    client_ip = get_remote_address(request)

    try:
        result = await rpc_report_client_error(
            machine_fingerprint=body.machine_fingerprint,
            license_mode=body.license_mode,
            error_type=body.error_type,
            error_message=body.error_message,
            bot_version=body.bot_version,
            client_ip=client_ip,
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "report_client_error RPC HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(status_code=502, detail="error_report_backend_error")
    except Exception as exc:
        logger.exception("report_client_error RPC failed: %s", exc)
        raise HTTPException(status_code=502, detail="error_report_backend_error")

    return result


@app.post("/v1/trial/heartbeat")
@limiter.limit("120/minute")
async def trial_heartbeat(request: Request, body: TrialHeartbeatRequest) -> dict:
    client_ip = get_remote_address(request)

    try:
        result = await rpc_trial_heartbeat(
            machine_fingerprint=body.machine_fingerprint,
            elapsed_seconds=body.elapsed_seconds,
            client_ip=client_ip,
        )
    except httpx.HTTPStatusError as exc:
        logger.error(
            "trial_heartbeat RPC HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(status_code=502, detail="trial_backend_error")
    except Exception as exc:
        logger.exception("trial_heartbeat RPC failed: %s", exc)
        raise HTTPException(status_code=502, detail="trial_backend_error")

    return result


@app.post("/v1/stripe/webhook")
async def stripe_webhook(request: Request) -> Response:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        return JSONResponse(status_code=503, content={"error": "webhook_not_configured"})

    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        await process_webhook(raw_body, sig_header)
    except stripe.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except ValueError as exc:
        if "webhook_not_configured" in str(exc):
            return JSONResponse(status_code=503, content={"error": "webhook_not_configured"})
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unhandled error in Stripe webhook: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return Response(status_code=200)
