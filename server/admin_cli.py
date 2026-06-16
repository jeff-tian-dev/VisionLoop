"""Admin CLI — talks to Supabase via PostgREST (IPv4-safe HTTPS).

Usage on the VM:

    sudo -u licapi bash -lc 'set -a; source /etc/license-api.env; set +a; \\
      /opt/license-api/.venv/bin/python -m server.admin_cli issue --email you@example.com'
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import click
import requests

from .keys import generate_license_key
from .license_extend import ExtendError, extend_license, result_to_dict


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


@cli.command()
@click.argument("key")
@click.option("--days", type=int, default=None, help="Whole days to add (must be positive).")
@click.option("--months", type=int, default=None, help="Whole calendar months to add.")
@click.option("--notes", default="")
@click.option("--dry-run", is_flag=True, help="Preview without updating Stripe or Postgres.")
def extend(key: str, days: int | None, months: int | None, notes: str, dry_run: bool) -> None:
    """Extend a license's access window.

    Timed/month-bundle keys: bumps licenses.expires_at from max(now, expires_at).
    Subscription-backed keys: also pushes Stripe trial_end so webhooks stay in sync.
    """
    if days is None and months is None:
        click.echo("Provide --days or --months", err=True)
        sys.exit(1)
    if days is not None and months is not None:
        click.echo("Use only one of --days or --months", err=True)
        sys.exit(1)

    try:
        result = extend_license(
            key=key,
            days=days,
            months=months,
            notes=notes or None,
            dry_run=dry_run,
        )
    except ExtendError as exc:
        _out({"error": exc.code, "message": exc.message, **exc.details})
        sys.exit(1)

    _out(result_to_dict(result))


if __name__ == "__main__":
    cli()
