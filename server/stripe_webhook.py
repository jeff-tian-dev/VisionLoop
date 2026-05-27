from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import stripe
from dateutil.parser import parse as parse_dt
from dateutil.relativedelta import relativedelta

from .db import (
    fetch_license_by_key,
    fetch_license_ids_by_session,
    insert_license_row,
    patch_license_by_subscription,
    patch_license_expires_at_by_key,
    try_claim_stripe_fulfillment,
)
from .email_client import send_license_email
from .keys import LICENSE_KEY_RE, generate_license_key
from .settings import get_settings

logger = logging.getLogger(__name__)


def _event_object_to_dict(obj: object) -> dict:
    """Stripe Webhook.construct_event returns StripeObjects — use plain dicts internally."""
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return dict(obj)


def _subscription_id(raw: object) -> str | None:
    if isinstance(raw, str) and raw.startswith("sub_"):
        return raw
    if isinstance(raw, dict):
        sid = raw.get("id")
        if isinstance(sid, str):
            return sid
    return None


def _customer_id_from_session(session: dict) -> str | None:
    cust = session.get("customer")
    if isinstance(cust, dict):
        cid = cust.get("id")
        return str(cid) if cid else None
    if isinstance(cust, str) and cust.startswith("cus_"):
        return cust
    return None


def _payment_intent_id_from_session(session: dict) -> str | None:
    pi = session.get("payment_intent")
    if isinstance(pi, dict):
        pid = pi.get("id")
        return str(pid) if pid else None
    if isinstance(pi, str) and pi.startswith("pi_"):
        return pi
    return None


def _extract_current_period_end(sub_obj: object) -> int | None:
    """Return current_period_end as a Unix timestamp from a subscription object or dict.

    Stripe API >= 2026-04-22.dahlia moved current_period_end from the top-level
    subscription object to items.data[0].current_period_end.  We check both
    locations so the code works across API versions.
    """
    # Top-level (older API / some webhook shapes still include it here)
    if isinstance(sub_obj, dict):
        ts = sub_obj.get("current_period_end")
    else:
        ts = getattr(sub_obj, "current_period_end", None)
    if ts is not None:
        return int(ts)

    # New API: items.data[0].current_period_end
    try:
        if isinstance(sub_obj, dict):
            items = sub_obj.get("items") or {}
            data = items.get("data") if isinstance(items, dict) else None
        else:
            items = getattr(sub_obj, "items", None)
            data = getattr(items, "data", None) if items is not None else None

        if isinstance(data, list) and data:
            first = data[0]
            item_ts = (
                first.get("current_period_end")
                if isinstance(first, dict)
                else getattr(first, "current_period_end", None)
            )
            if item_ts is not None:
                return int(item_ts)
    except Exception:
        pass

    return None


def _fetch_subscription_period_end_iso(subscription_id: str) -> str | None:
    sub = stripe.Subscription.retrieve(subscription_id, expand=["items"])
    ts = _extract_current_period_end(sub)
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _period_end_iso_from_sub_dict(sub: dict) -> str | None:
    ts = _extract_current_period_end(sub)
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _expires_iso_from_deleted_sub(sub: dict) -> str:
    """End access at Stripe's ended_at, else current_period_end, else now."""
    ended = sub.get("ended_at")
    if ended is not None:
        return datetime.fromtimestamp(int(ended), tz=timezone.utc).isoformat()
    ts = _extract_current_period_end(sub)
    if ts is not None:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _customer_id_from_sub_dict(sub: dict) -> str | None:
    cust = sub.get("customer")
    if isinstance(cust, str) and cust.startswith("cus_"):
        return cust
    if isinstance(cust, dict):
        cid = cust.get("id")
        return str(cid) if cid else None
    return None


def _line_items_price_qty(session: dict) -> list[tuple[str, int]]:
    lis = session.get("line_items") or {}
    data = lis.get("data") if isinstance(lis, dict) else None
    if not isinstance(data, list):
        return []
    out: list[tuple[str, int]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        qty = int(item.get("quantity") or 1)
        price_obj = item.get("price")
        pid: str | None = None
        if isinstance(price_obj, str):
            pid = price_obj
        elif isinstance(price_obj, dict):
            p = price_obj.get("id")
            pid = str(p) if p else None
        if pid:
            out.append((pid, qty))
    return out


def _custom_field_text(session: dict, key: str) -> str:
    raw = session.get("custom_fields") or []
    if not isinstance(raw, list):
        return ""
    for field in raw:
        if not isinstance(field, dict):
            continue
        if field.get("key") != key:
            continue
        text_obj = field.get("text")
        if isinstance(text_obj, dict):
            val = text_obj.get("value")
            return str(val).strip() if val is not None else ""
        val = field.get("value")
        return str(val).strip() if val is not None else ""
    return ""


def _months_for_price(pq: list[tuple[str, int]], price_id: str) -> int:
    pid = price_id.strip()
    return sum(q for p, q in pq if p == pid)


async def _retrieve_checkout_session(session_id: str) -> dict:
    def fetch() -> dict:
        sess = stripe.checkout.Session.retrieve(
            session_id,
            expand=["line_items.data.price"],
        )
        return _event_object_to_dict(sess)

    return await asyncio.to_thread(fetch)


def _expires_at_datetime(row: dict | None) -> datetime | None:
    raw = row.get("expires_at") if row else None
    if not raw:
        return None
    dt = parse_dt(str(raw))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_new_expiry(
    *, now: datetime, current_expires: datetime | None, months: int
) -> datetime:
    """Stack +N months after max(now, current_expires).

    Lifetime (expires_at null) or brand-new mint: pass current_expires=None → anchors at now.
    """
    if months <= 0:
        raise ValueError("months must be positive")
    if current_expires is None:
        base = now
    else:
        base = max(now, current_expires)
    return base + relativedelta(months=months)


async def handle_checkout_completed(raw_session: dict) -> None:
    """Fulfill Stripe checkout: lifetime one-time, N-month bundle (extend or mint), or subscription."""
    session_id = raw_session.get("id")
    if not session_id or not isinstance(session_id, str):
        logger.error("checkout.session.completed payload missing session id")
        return

    session = await _retrieve_checkout_session(session_id)

    customer_details = session.get("customer_details") or {}
    customer_email: str | None = customer_details.get("email")
    if not customer_email:
        customer_email = session.get("receipt_email") or session.get("customer_email")
    if not customer_email:
        logger.error("Stripe checkout %s has no customer email — cannot deliver key", session_id)
        return

    settings = get_settings()
    pq = _line_items_price_qty(session)

    stripe_customer_id = _customer_id_from_session(session)
    stripe_payment_intent = _payment_intent_id_from_session(session)
    lifetime_price = (settings.stripe_price_id or "").strip()
    extend_price = settings.month_extend_price_id()

    mode = session.get("mode")

    if mode == "subscription":
        await _checkout_subscription_license(
            session=session,
            customer_email=customer_email,
            stripe_customer_id=stripe_customer_id,
        )
        return

    if mode != "payment":
        logger.warning(
            "checkout %s unsupported mode=%r — skipping",
            session_id,
            mode,
        )
        return

    has_lifetime = bool(lifetime_price) and _months_for_price(pq, lifetime_price) > 0
    extend_months = _months_for_price(pq, extend_price) if extend_price else 0
    has_extend = extend_months > 0

    if has_lifetime and has_extend:
        logger.error(
            "checkout %s mixes lifetime + month-extend SKUs — not supported",
            session_id,
        )
        return

    if has_lifetime:
        await _lifetime_payment_checkout(
            session_id=session_id,
            customer_email=customer_email,
            stripe_customer_id=stripe_customer_id,
            stripe_payment_intent=stripe_payment_intent,
        )
        return

    if has_extend:
        await _month_extend_bundle_checkout(
            session_id=session_id,
            session=session,
            customer_email=customer_email,
            stripe_customer_id=stripe_customer_id,
            stripe_payment_intent=stripe_payment_intent,
            extend_months=extend_months,
        )
        return

    logger.warning(
        "checkout %s payment mode but no configured price id matched line items",
        session_id,
    )


async def _checkout_subscription_license(
    *,
    session: dict,
    customer_email: str,
    stripe_customer_id: str | None,
) -> None:
    """Legacy Stripe subscription Checkout — mint timed license keyed on subscription."""
    session_id = session.get("id")

    stripe_subscription_id = _subscription_id(session.get("subscription"))
    if not stripe_subscription_id:
        logger.error(
            "Stripe subscription checkout %s missing subscription id",
            session_id,
        )
        return

    expires_at = await asyncio.to_thread(
        _fetch_subscription_period_end_iso,
        stripe_subscription_id,
    )
    if not expires_at:
        logger.error(
            "Stripe subscription %s missing current_period_end",
            stripe_subscription_id,
        )
        return

    license_key = generate_license_key()
    inserted = await insert_license_row(
        license_key=license_key,
        email=customer_email,
        stripe_customer_id=stripe_customer_id,
        stripe_payment_intent=None,
        stripe_checkout_session_id=session_id,
        expires_at=expires_at,
        stripe_subscription_id=stripe_subscription_id,
    )

    if not inserted:
        logger.info(
            "Duplicate webhook for subscription session %s — skipping email",
            session_id,
        )
        return

    logger.info(
        "New subscription license %s issued for %s (session %s)",
        license_key,
        customer_email,
        session_id,
    )
    await _safe_send_license_email(
        customer_email,
        license_key,
        fulfillment_type="subscription",
        expires_at_iso=expires_at,
    )


async def _lifetime_payment_checkout(
    *,
    session_id: str,
    customer_email: str,
    stripe_customer_id: str | None,
    stripe_payment_intent: str | None,
) -> None:
    if await fetch_license_ids_by_session(session_id):
        logger.info(
            "checkout %s already has a license row — skipping lifetime replay",
            session_id,
        )
        return

    claimed = await try_claim_stripe_fulfillment(
        stripe_checkout_session_id=session_id,
        variant="lifetime_new",
    )
    if not claimed:
        logger.info(
            "Duplicate webhook for checkout %s — lifetime fulfillment already claimed",
            session_id,
        )
        return

    license_key = generate_license_key()
    inserted = await insert_license_row(
        license_key=license_key,
        email=customer_email,
        stripe_customer_id=stripe_customer_id,
        stripe_payment_intent=stripe_payment_intent,
        stripe_checkout_session_id=session_id,
        expires_at=None,
        stripe_subscription_id=None,
    )

    if not inserted:
        logger.error(
            "Fulfillment claimed for lifetime session %s but license insert skipped — manual fix",
            session_id,
        )
        return

    logger.info(
        "New lifetime license %s issued for %s (session %s)",
        license_key,
        customer_email,
        session_id,
    )
    await _safe_send_license_email(
        customer_email,
        license_key,
        fulfillment_type="lifetime",
        expires_at_iso=None,
    )


async def _month_extend_bundle_checkout(
    *,
    session_id: str,
    session: dict,
    customer_email: str,
    stripe_customer_id: str | None,
    stripe_payment_intent: str | None,
    extend_months: int,
) -> None:
    raw_key = _custom_field_text(session, "existing_license_key").upper()
    stripped = raw_key.strip()
    extending_row: dict | None = None
    extend_variant = "month_bundle_new"

    if stripped:
        if not re.fullmatch(LICENSE_KEY_RE, stripped):
            logger.critical(
                "checkout %s existing_license_key field present but malformed — minting NEW timed key "
                "(user may need support to merge billing)",
                session_id,
            )
        else:
            row = await fetch_license_by_key(stripped)
            if row:
                extending_row = row
                extend_variant = "month_extend"
            else:
                logger.warning(
                    "checkout %s key %s normalized valid but no license row — minting NEW timed key",
                    session_id,
                    stripped[:10],
                )

    if extending_row is None and await fetch_license_ids_by_session(session_id):
        logger.info(
            "checkout %s already linked to a license row — skipping month-bundle mint replay",
            session_id,
        )
        return

    claimed = await try_claim_stripe_fulfillment(
        stripe_checkout_session_id=session_id,
        variant=extend_variant,
    )
    if not claimed:
        logger.info(
            "Duplicate webhook for checkout %s — month bundle fulfillment already claimed",
            session_id,
        )
        return

    now = datetime.now(timezone.utc)

    if extending_row:
        license_key_for_email = extending_row.get("license_key") or stripped
        cur_dt = _expires_at_datetime(extending_row)
        new_dt = compute_new_expiry(now=now, current_expires=cur_dt, months=extend_months)
        new_exp_iso = new_dt.isoformat()

        n = await patch_license_expires_at_by_key(
            license_key=str(license_key_for_email),
            expires_at=new_exp_iso,
            stripe_customer_id=stripe_customer_id,
            stripe_payment_intent=stripe_payment_intent,
        )
        if n == 0:
            logger.error(
                "checkout %s extend PATCH matched 0 rows for key fragment %s — manual fix",
                session_id,
                str(license_key_for_email)[:12],
            )
            return
        logger.info(
            "Extended license %s to %s (+ %s months, session %s)",
            license_key_for_email,
            new_exp_iso,
            extend_months,
            session_id,
        )
        await _safe_send_license_email(
            customer_email,
            str(license_key_for_email),
            fulfillment_type="extend",
            expires_at_iso=new_exp_iso,
        )
        return

    license_key = generate_license_key()
    new_dt = compute_new_expiry(now=now, current_expires=None, months=extend_months)
    new_exp_iso = new_dt.isoformat()
    inserted = await insert_license_row(
        license_key=license_key,
        email=customer_email,
        stripe_customer_id=stripe_customer_id,
        stripe_payment_intent=stripe_payment_intent,
        stripe_checkout_session_id=session_id,
        expires_at=new_exp_iso,
        stripe_subscription_id=None,
    )
    if not inserted:
        logger.error(
            "Fulfillment claimed for month-bundle session %s but license insert failed — manual fix",
            session_id,
        )
        return
    logger.info(
        "New timed-access license %s for %s until %s (%s mo, session %s)",
        license_key,
        customer_email,
        new_exp_iso,
        extend_months,
        session_id,
    )
    await _safe_send_license_email(
        customer_email,
        license_key,
        fulfillment_type="timed_new",
        expires_at_iso=new_exp_iso,
    )


async def _safe_send_license_email(
    to_email: str,
    license_key: str,
    *,
    fulfillment_type: str,
    expires_at_iso: str | None,
) -> None:
    try:
        await send_license_email(
            to_email,
            license_key,
            fulfillment_type=fulfillment_type,
            expires_at_iso=expires_at_iso,
        )
    except Exception as exc:
        logger.error("Email delivery failed for %s: %s", to_email, exc)


async def handle_subscription_updated(sub: dict) -> None:
    sub_id = _subscription_id(sub)
    if not sub_id:
        logger.warning("subscription.updated payload missing id")
        return
    expires_at = _period_end_iso_from_sub_dict(sub)
    if not expires_at:
        logger.warning(
            "subscription.updated %s missing current_period_end",
            sub_id,
        )
        return
    n = await patch_license_by_subscription(
        stripe_subscription_id=sub_id,
        expires_at=expires_at,
        stripe_customer_id=_customer_id_from_sub_dict(sub),
    )
    if n == 0:
        logger.warning(
            "subscription.updated %s: no license row matched (yet?)",
            sub_id,
        )
    else:
        logger.info(
            "subscription.updated %s → expires_at %s",
            sub_id,
            expires_at,
        )


async def handle_subscription_deleted(sub: dict) -> None:
    sub_id = _subscription_id(sub)
    if not sub_id:
        logger.warning("subscription.deleted payload missing id")
        return
    expires_at = _expires_iso_from_deleted_sub(sub)
    n = await patch_license_by_subscription(
        stripe_subscription_id=sub_id,
        expires_at=expires_at,
        stripe_customer_id=_customer_id_from_sub_dict(sub),
    )
    if n == 0:
        logger.warning(
            "subscription.deleted %s: no license row matched",
            sub_id,
        )
    else:
        logger.info(
            "subscription.deleted %s → expires_at %s",
            sub_id,
            expires_at,
        )


async def process_webhook(raw_body: bytes, sig_header: str) -> None:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise ValueError("webhook_not_configured")

    event = stripe.Webhook.construct_event(
        payload=raw_body,
        sig_header=sig_header,
        secret=settings.stripe_webhook_secret,
        tolerance=300,
    )

    logger.info("Stripe event received: %s", event["type"])

    etype = event["type"]
    if etype == "checkout.session.completed":
        await handle_checkout_completed(_event_object_to_dict(event["data"]["object"]))
    elif etype == "customer.subscription.updated":
        await handle_subscription_updated(
            _event_object_to_dict(event["data"]["object"])
        )
    elif etype == "customer.subscription.deleted":
        await handle_subscription_deleted(
            _event_object_to_dict(event["data"]["object"])
        )
