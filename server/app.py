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
from .db import close_pool, init_pool, ping, rpc_trial_heartbeat, rpc_unpair_license, rpc_validate_license
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
