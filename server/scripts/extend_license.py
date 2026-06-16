"""Extend a license key's paid access window (admin).

Handles both timed/month-bundle keys (DB only) and legacy Stripe subscription-backed
keys (updates Stripe trial_end first, then Postgres).

GUI (local admin popup)::

    python -m server.scripts.extend_license_gui

Usage on the VM::

    sudo -u licapi bash -lc 'set -a; source /etc/license-api.env; set +a; \\
      /opt/license-api/.venv/bin/python -m server.scripts.extend_license CLASH-XXXX --days 30'

Preview without applying::

    python -m server.scripts.extend_license CLASH-XXXX --months 1 --dry-run

Requires SUPABASE_URL, SUPABASE_ANON_KEY, and STRIPE_SECRET_KEY (only when the row
has stripe_subscription_id).
"""
from __future__ import annotations

import json
import sys

import click

from server.license_extend import ExtendError, extend_license, result_to_dict


@click.command()
@click.argument("key")
@click.option("--days", type=int, default=None, help="Whole days to add.")
@click.option("--months", type=int, default=None, help="Whole months to add (calendar months).")
@click.option("--notes", default="", help="Optional note stored on the license row.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show the planned change without updating Stripe or Postgres.",
)
def main(key: str, days: int | None, months: int | None, notes: str, dry_run: bool) -> None:
    """Extend CLASH-… access; syncs Stripe when stripe_subscription_id is set."""
    if days is None and months is None:
        raise click.UsageError("Provide --days or --months")
    if days is not None and months is not None:
        raise click.UsageError("Use only one of --days or --months")

    try:
        result = extend_license(
            key=key,
            days=days,
            months=months,
            notes=notes or None,
            dry_run=dry_run,
        )
    except ExtendError as exc:
        payload = {"error": exc.code, "message": exc.message, **exc.details}
        click.echo(json.dumps(payload, indent=2))
        sys.exit(1)
    except Exception as exc:
        click.echo(json.dumps({"error": "unexpected", "message": str(exc)}, indent=2))
        sys.exit(1)

    click.echo(json.dumps(result_to_dict(result), indent=2, default=str))


if __name__ == "__main__":
    main()
