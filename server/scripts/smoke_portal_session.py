"""Smoke-test the Stripe customer portal used by /v1/portal.

Resolves a Stripe customer from a license key, an email, or a cus_… id, then creates
a billing portal session and prints the URL.  Use it to confirm the portal
configuration is activated for the current Stripe mode before shipping a build.

Usage (on VM):
    sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \
      cd /opt/license-api && /opt/license-api/.venv/bin/python -m server.scripts.smoke_portal_session \
        --email customer@example.com'

    ... --key CLASH-XXXX-XXXX-XXXX-XXXX
    ... --customer cus_XXXXXXXX
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import stripe

from ..db import close_pool, fetch_license_billing_by_key, init_pool


async def _customer_id_for_key(license_key: str) -> str | None:
    await init_pool()
    try:
        row = await fetch_license_billing_by_key(license_key.upper().strip())
    finally:
        await close_pool()
    if not row:
        print(f"No license row for {license_key}", file=sys.stderr)
        return None
    cid = str(row.get("stripe_customer_id") or "").strip()
    if cid:
        return cid
    email = str(row.get("email") or "").strip()
    if not email:
        return None
    print(f"License has no stripe_customer_id — falling back to email {email}")
    return _customer_id_for_email(email)


def _customer_id_for_email(email: str) -> str | None:
    result = stripe.Customer.list(email=email.strip(), limit=1)
    data = getattr(result, "data", None) or []
    for cust in data:
        cid = cust.get("id") if isinstance(cust, dict) else getattr(cust, "id", None)
        if cid:
            return str(cid)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--key", help="License key to resolve a Stripe customer from")
    group.add_argument("--email", help="Customer email to look up in Stripe")
    group.add_argument("--customer", help="Stripe customer id (cus_...)")
    args = parser.parse_args()

    secret = os.environ.get("STRIPE_SECRET_KEY")
    if not secret:
        print("Need STRIPE_SECRET_KEY in env", file=sys.stderr)
        sys.exit(1)
    stripe.api_key = secret.strip()

    if args.customer:
        customer_id = args.customer.strip()
    elif args.email:
        customer_id = _customer_id_for_email(args.email)
    else:
        customer_id = asyncio.run(_customer_id_for_key(args.key))

    if not customer_id:
        print("No Stripe customer found — /v1/portal would return no_billing_account", file=sys.stderr)
        sys.exit(1)

    return_url = os.environ.get(
        "STRIPE_PORTAL_RETURN_URL", "https://clashautoloot.duckdns.org/?portal=done"
    )
    kwargs: dict = {"customer": customer_id, "return_url": return_url}
    configuration = (os.environ.get("STRIPE_PORTAL_CONFIGURATION_ID") or "").strip()
    if configuration:
        kwargs["configuration"] = configuration

    try:
        session = stripe.billing_portal.Session.create(**kwargs)
    except stripe.InvalidRequestError as exc:
        message = str(getattr(exc, "user_message", "") or exc)
        print(f"Stripe rejected the portal session: {message}", file=sys.stderr)
        if "configuration" in message.lower():
            print(
                "Activate the portal at Dashboard → Settings → Billing → Customer portal "
                "(test and live modes are configured separately).",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"Customer   : {customer_id}")
    print(f"Return URL : {return_url}")
    if configuration:
        print(f"Config     : {configuration}")
    print()
    print("Open this URL in your browser (single use, expires shortly):")
    print(session.url)


if __name__ == "__main__":
    main()
