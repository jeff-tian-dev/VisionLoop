"""Admin CLI — talks to Supabase via PostgREST (IPv4-safe HTTPS).

Usage on the VM:

    sudo -u licapi bash -lc 'set -a; source /etc/license-api.env; set +a; \\
      /opt/license-api/.venv/bin/python -m server.admin_cli issue --email you@example.com'
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import click
import requests
from dateutil.parser import parse as parse_dt

from .keys import generate_license_key


def _headers() -> dict[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        click.echo(
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set (source /etc/license-api.env)",
            err=True,
        )
        sys.exit(2)
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _rest_base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"


def _out(data: object) -> None:
    click.echo(json.dumps(data, indent=2, default=str))


def _get(path: str, params: dict[str, str] | None = None) -> requests.Response:
    return requests.get(_rest_base() + path, headers=_headers(), params=params or {}, timeout=30)


def _patch(path: str, *, params: dict[str, str], json_body: dict[str, Any]) -> requests.Response:
    return requests.patch(
        _rest_base() + path,
        headers=_headers(),
        params=params,
        json=json_body,
        timeout=30,
    )


def _post(path: str, json_body: dict[str, Any], *, prefer: str | None = None) -> requests.Response:
    h = dict(_headers())
    if prefer:
        h["Prefer"] = prefer
    return requests.post(_rest_base() + path, headers=h, json=json_body, timeout=30)


def _delete(path: str, *, params: dict[str, str]) -> requests.Response:
    return requests.delete(_rest_base() + path, headers=_headers(), params=params, timeout=30)


@click.group()
def cli() -> None:
    """Clash Auto Loot license administration (Supabase REST)."""


@cli.command()
@click.option("--email", required=True)
@click.option("--notes", default="")
def issue(email: str, notes: str) -> None:
    key = generate_license_key()
    body: dict[str, Any] = {
        "license_key": key,
        "status": "active",
        "email": email,
    }
    if notes:
        body["notes"] = notes

    r = _post("/licenses", body, prefer="return=representation")
    if r.status_code not in (200, 201):
        _out({"error": r.text, "status": r.status_code})
        sys.exit(1)
    rows = r.json()
    row = rows[0] if isinstance(rows, list) and rows else rows
    _out({"issued": True, **row})


@cli.command()
@click.argument("key")
@click.option("--notes", default="")
def revoke(key: str, notes: str) -> None:
    patch_body: dict[str, Any] = {
        "status": "revoked",
        "revoked_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        patch_body["notes"] = notes

    r = _patch("/licenses", params={"license_key": f"eq.{key}"}, json_body=patch_body)

    if r.status_code in (404, 406):
        _out({"error": "Key not found", "key": key})
        sys.exit(1)
    if r.status_code not in (200, 204):
        _out({"error": r.text, "status": r.status_code})
        sys.exit(1)

    _out({"revoked": True, "key": key})


@cli.command()
@click.option("--key", default=None)
@click.option("--email", default=None)
def lookup(key: str | None, email: str | None) -> None:
    if not key and not email:
        click.echo("Provide --key or --email", err=True)
        sys.exit(1)

    params: dict[str, str] = {"select": "*"}
    if key:
        params["license_key"] = f"eq.{key}"
    else:
        params["email"] = f"eq.{email}"

    r = _get("/licenses", params=params)
    r.raise_for_status()
    licenses = r.json()
    if not licenses:
        _out({"found": False})
        sys.exit(1)

    enriched = []
    for lic in licenses:
        lid = lic["id"]
        mr = _get("/license_machines", params={"select": "*", "license_id": f"eq.{lid}"})
        mr.raise_for_status()
        machines = mr.json()
        row = dict(lic)
        row["_machine"] = machines[0] if machines else None
        enriched.append(row)

    _out({"found": True, "count": len(enriched), "licenses": enriched})


@cli.command("reset-machine")
@click.argument("key")
def reset_machine(key: str) -> None:
    r = _get("/licenses", params={"select": "id", "license_key": f"eq.{key}", "limit": "1"})
    r.raise_for_status()
    rows = r.json()
    if not rows:
        _out({"error": "Key not found", "key": key})
        sys.exit(1)

    lic_id = rows[0]["id"]
    dr = _delete("/license_machines", params={"license_id": f"eq.{lic_id}"})

    if dr.status_code not in (200, 204):
        _out({"error": dr.text, "status": dr.status_code})
        sys.exit(1)

    _out({"reset": True, "key": key, "message": "Machine binding removed (if any)."})


def _parse_expires(raw: object) -> datetime | None:
    if not raw:
        return None
    dt = parse_dt(str(raw))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stripe_period_end_ts(sub: object) -> int | None:
    """current_period_end as a Unix ts, checking both old top-level and new item locations."""
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


def _extend_stripe_subscription(subscription_id: str, days: int) -> str:
    """Push the subscription's next billing date out by N days (no proration).

    Returns the new period end as an ISO timestamp. Raises on misconfiguration so
    the caller can avoid a half-applied extension.
    """
    secret = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "STRIPE_SECRET_KEY not set — cannot extend a subscription-backed key "
            "(source /etc/license-api.env)"
        )
    import stripe

    stripe.api_key = secret
    sub = stripe.Subscription.retrieve(subscription_id, expand=["items"])
    period_end = _stripe_period_end_ts(sub)
    if period_end is None:
        raise RuntimeError(f"Subscription {subscription_id} has no current_period_end")
    new_end = period_end + days * 86400
    stripe.Subscription.modify(
        subscription_id,
        trial_end=new_end,
        proration_behavior="none",
    )
    return datetime.fromtimestamp(new_end, tz=timezone.utc).isoformat()


@cli.command()
@click.argument("key")
@click.option("--days", type=int, required=True, help="Whole days to add (must be positive).")
@click.option("--notes", default="")
def extend(key: str, days: int, notes: str) -> None:
    """Extend a license's access window by N days.

    Timed/month-bundle keys: bumps licenses.expires_at to max(now, expires_at) + N days.
    Subscription-backed keys: also pushes Stripe's next billing date (trial_end) so the
    customer.subscription.updated webhook won't revert the change.
    Lifetime keys (no expiry) are refused — they already have unlimited access.
    """
    if days <= 0:
        click.echo("--days must be a positive integer", err=True)
        sys.exit(1)

    r = _get("/licenses", params={"select": "*", "license_key": f"eq.{key}", "limit": "1"})
    r.raise_for_status()
    rows = r.json()
    if not rows:
        _out({"error": "Key not found", "key": key})
        sys.exit(1)
    lic = rows[0]

    if lic.get("status") == "revoked":
        _out({"error": "Key is revoked — extending will not restore access", "key": key})
        sys.exit(1)

    sub_id = lic.get("stripe_subscription_id")
    cur_dt = _parse_expires(lic.get("expires_at"))

    if cur_dt is None and not sub_id:
        _out({
            "error": "Key has no expiry (lifetime) — nothing to extend",
            "key": key,
        })
        sys.exit(1)

    now = datetime.now(timezone.utc)

    if sub_id:
        try:
            new_exp_iso = _extend_stripe_subscription(str(sub_id), days)
        except Exception as exc:
            _out({"error": f"Stripe extend failed: {exc}", "key": key, "subscription": sub_id})
            sys.exit(1)
    else:
        base = max(now, cur_dt) if cur_dt else now
        new_exp_iso = (base + timedelta(days=days)).isoformat()

    patch_body: dict[str, Any] = {"expires_at": new_exp_iso}
    if notes:
        patch_body["notes"] = notes

    pr = _patch("/licenses", params={"license_key": f"eq.{key}"}, json_body=patch_body)
    if pr.status_code in (404, 406):
        _out({"error": "Key not found", "key": key})
        sys.exit(1)
    if pr.status_code not in (200, 204):
        _out({"error": pr.text, "status": pr.status_code})
        sys.exit(1)

    _out({
        "extended": True,
        "key": key,
        "days": days,
        "expires_at": new_exp_iso,
        "subscription": sub_id,
        "previous_expires_at": lic.get("expires_at"),
    })


if __name__ == "__main__":
    cli()
