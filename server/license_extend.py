"""Admin license extension — DB-only timed keys vs Stripe subscription-backed keys.

Subscription-backed keys must update Stripe (trial_end) before Postgres so
``customer.subscription.updated`` does not revert a DB-only patch.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import requests
from dateutil.parser import parse as parse_dt
from dateutil.relativedelta import relativedelta

ExtendKind = Literal["timed", "stripe_subscription", "lifetime", "revoked"]


class ExtendError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ExtendPlan:
    key: str
    kind: ExtendKind
    days: int
    previous_expires_at: str | None
    new_expires_at: str
    stripe_subscription_id: str | None
    stripe_status: str | None
    anchor_expires_at: str
    notes: str | None


@dataclass(frozen=True)
class ExtendResult:
    plan: ExtendPlan
    applied: bool


def _headers() -> dict[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise ExtendError(
            "missing_credentials",
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set (source /etc/license-api.env)",
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _rest_base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"


def parse_expires(raw: object) -> datetime | None:
    if not raw:
        return None
    dt = parse_dt(str(raw))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stripe_period_end_ts(sub: object) -> int | None:
    ts = getattr(sub, "current_period_end", None)
    if ts is not None:
        return int(ts)
    items = getattr(sub, "items", None)
    data = getattr(items, "data", None) if items is not None else None
    if isinstance(data, list) and data:
        item_ts = getattr(data[0], "current_period_end", None)
        if item_ts is not None:
            return int(item_ts)
    return None


def compute_extended_expiry(
    *,
    now: datetime,
    current_expires: datetime | None,
    stripe_period_end: datetime | None,
    days: int,
) -> datetime:
    if days <= 0:
        raise ExtendError("invalid_days", "Extension must be a positive number of days")
    anchors = [now]
    if current_expires is not None:
        anchors.append(current_expires)
    if stripe_period_end is not None:
        anchors.append(stripe_period_end)
    return max(anchors) + timedelta(days=days)


def compute_extended_expiry_months(
    *,
    now: datetime,
    current_expires: datetime | None,
    stripe_period_end: datetime | None,
    months: int,
) -> datetime:
    if months <= 0:
        raise ExtendError("invalid_months", "Extension must be a positive number of months")
    anchors = [now]
    if current_expires is not None:
        anchors.append(current_expires)
    if stripe_period_end is not None:
        anchors.append(stripe_period_end)
    return max(anchors) + relativedelta(months=months)


def fetch_license_by_key(key: str) -> dict[str, Any] | None:
    r = requests.get(
        _rest_base() + "/licenses",
        headers=_headers(),
        params={"select": "*", "license_key": f"eq.{key}", "limit": "1"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    return rows[0]


def _retrieve_stripe_subscription(subscription_id: str) -> tuple[object, datetime | None, str | None]:
    secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise ExtendError(
            "missing_stripe_key",
            "STRIPE_SECRET_KEY not set — cannot extend a subscription-backed key "
            "(source /etc/license-api.env)",
            details={"stripe_subscription_id": subscription_id},
        )
    import stripe

    stripe.api_key = secret
    sub = stripe.Subscription.retrieve(subscription_id, expand=["items"])
    period_end_ts = _stripe_period_end_ts(sub)
    period_end = (
        datetime.fromtimestamp(period_end_ts, tz=timezone.utc) if period_end_ts is not None else None
    )
    status = getattr(sub, "status", None)
    return sub, period_end, str(status) if status is not None else None


def plan_extend(
    *,
    key: str,
    days: int | None = None,
    months: int | None = None,
    notes: str | None = None,
) -> ExtendPlan:
    if (days is None) == (months is None):
        raise ExtendError("invalid_duration", "Provide exactly one of days or months")

    normalized_key = key.strip().upper()
    lic = fetch_license_by_key(normalized_key)
    if lic is None:
        raise ExtendError("not_found", f"License key not found: {normalized_key}")

    if lic.get("status") == "revoked":
        raise ExtendError(
            "revoked",
            "Key is revoked — extend access after re-activating the license row",
            details={"key": normalized_key},
        )

    sub_id_raw = lic.get("stripe_subscription_id")
    sub_id = str(sub_id_raw).strip() if sub_id_raw else ""
    cur_dt = parse_expires(lic.get("expires_at"))
    now = datetime.now(timezone.utc)

    stripe_period_end: datetime | None = None
    stripe_status: str | None = None

    if sub_id:
        _, stripe_period_end, stripe_status = _retrieve_stripe_subscription(sub_id)
        if stripe_status in {"canceled", "incomplete_expired"}:
            raise ExtendError(
                "stripe_subscription_inactive",
                f"Stripe subscription {sub_id} is {stripe_status} — "
                "reactivate in Stripe or clear stripe_subscription_id before a DB-only extend",
                details={"stripe_subscription_id": sub_id, "stripe_status": stripe_status},
            )
        if stripe_period_end is None:
            raise ExtendError(
                "stripe_missing_period_end",
                f"Stripe subscription {sub_id} has no current_period_end",
                details={"stripe_subscription_id": sub_id},
            )
        kind: ExtendKind = "stripe_subscription"
    elif cur_dt is None:
        raise ExtendError(
            "lifetime",
            "Key has no expiry (lifetime) — nothing to extend",
            details={"key": normalized_key},
        )
    else:
        kind = "timed"

    if days is not None:
        new_dt = compute_extended_expiry(
            now=now,
            current_expires=cur_dt,
            stripe_period_end=stripe_period_end,
            days=days,
        )
        duration_days = days
    else:
        assert months is not None
        new_dt = compute_extended_expiry_months(
            now=now,
            current_expires=cur_dt,
            stripe_period_end=stripe_period_end,
            months=months,
        )
        duration_days = (new_dt - max(
            [now]
            + ([cur_dt] if cur_dt else [])
            + ([stripe_period_end] if stripe_period_end else [])
        )).days

    anchor_dt = max(
        [now]
        + ([cur_dt] if cur_dt else [])
        + ([stripe_period_end] if stripe_period_end else [])
    )

    return ExtendPlan(
        key=normalized_key,
        kind=kind,
        days=duration_days,
        previous_expires_at=lic.get("expires_at"),
        new_expires_at=new_dt.isoformat(),
        stripe_subscription_id=sub_id or None,
        stripe_status=stripe_status,
        anchor_expires_at=anchor_dt.isoformat(),
        notes=notes.strip() if notes and notes.strip() else None,
    )


def _push_stripe_trial_end(subscription_id: str, new_end: datetime) -> str:
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    new_end_ts = int(new_end.timestamp())
    stripe.Subscription.modify(
        subscription_id,
        trial_end=new_end_ts,
        proration_behavior="none",
    )
    return new_end.isoformat()


def _patch_license_expires(key: str, expires_at: str, notes: str | None) -> None:
    body: dict[str, Any] = {"expires_at": expires_at}
    if notes:
        body["notes"] = notes
    r = requests.patch(
        _rest_base() + "/licenses",
        headers=_headers(),
        params={"license_key": f"eq.{key}"},
        json=body,
        timeout=30,
    )
    if r.status_code in (404, 406):
        raise ExtendError("not_found", f"License key not found during patch: {key}")
    if r.status_code not in (200, 204):
        raise ExtendError(
            "patch_failed",
            f"Failed to update licenses.expires_at (HTTP {r.status_code})",
            details={"response": r.text},
        )


def apply_extend(plan: ExtendPlan, *, dry_run: bool = False) -> ExtendResult:
    new_exp_iso = plan.new_expires_at

    if plan.kind == "stripe_subscription":
        assert plan.stripe_subscription_id
        new_dt = parse_expires(plan.new_expires_at)
        assert new_dt is not None
        if not dry_run:
            try:
                new_exp_iso = _push_stripe_trial_end(plan.stripe_subscription_id, new_dt)
            except Exception as exc:
                raise ExtendError(
                    "stripe_modify_failed",
                    f"Stripe subscription update failed: {exc}",
                    details={"stripe_subscription_id": plan.stripe_subscription_id},
                ) from exc

    if not dry_run:
        _patch_license_expires(plan.key, new_exp_iso, plan.notes)

    applied_plan = ExtendPlan(
        key=plan.key,
        kind=plan.kind,
        days=plan.days,
        previous_expires_at=plan.previous_expires_at,
        new_expires_at=new_exp_iso,
        stripe_subscription_id=plan.stripe_subscription_id,
        stripe_status=plan.stripe_status,
        anchor_expires_at=plan.anchor_expires_at,
        notes=plan.notes,
    )
    return ExtendResult(plan=applied_plan, applied=not dry_run)


def extend_license(
    *,
    key: str,
    days: int | None = None,
    months: int | None = None,
    notes: str | None = None,
    dry_run: bool = False,
) -> ExtendResult:
    plan = plan_extend(key=key, days=days, months=months, notes=notes)
    return apply_extend(plan, dry_run=dry_run)


def result_to_dict(result: ExtendResult) -> dict[str, Any]:
    p = result.plan
    out: dict[str, Any] = {
        "extended": result.applied,
        "dry_run": not result.applied,
        "key": p.key,
        "kind": p.kind,
        "days": p.days,
        "anchor_expires_at": p.anchor_expires_at,
        "previous_expires_at": p.previous_expires_at,
        "expires_at": p.new_expires_at,
        "stripe_subscription_id": p.stripe_subscription_id,
        "stripe_status": p.stripe_status,
    }
    if p.kind == "stripe_subscription":
        out["stripe_action"] = "modify_trial_end"
        out["message"] = (
            "Stripe trial_end and licenses.expires_at updated — "
            "subscription.updated webhook should stay in sync"
        )
    elif p.kind == "timed":
        out["stripe_action"] = None
        out["message"] = "licenses.expires_at updated (no Stripe subscription on this key)"
    if p.notes:
        out["notes"] = p.notes
    return out
