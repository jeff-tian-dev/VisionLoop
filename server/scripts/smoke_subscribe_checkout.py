"""Smoke-test the /v1/checkout/subscribe flow end-to-end.

Creates a live Stripe Checkout Session in subscription mode using the configured
recurring price, optionally applying a coupon for $0 test runs.

Usage (on VM):
    sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \
      cd /opt/license-api && /opt/license-api/.venv/bin/python -m server.scripts.smoke_subscribe_checkout'

Or with a coupon:
    SMOKE_COUPON=VhpP0bXt python -m server.scripts.smoke_subscribe_checkout

Open the printed URL in a browser.  For a $0 run use the coupon code DEV_TEST_100PCT_OFF.
After completing checkout watch the VM logs:
    sudo journalctl -u license-api -f
"""
from __future__ import annotations

import os
import sys

import stripe


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID")
    coupon = os.environ.get("SMOKE_COUPON", "")

    if not key or not price_id:
        print("Need STRIPE_SECRET_KEY and STRIPE_SUBSCRIPTION_PRICE_ID in env", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = key.strip()
    price_id = price_id.strip()

    kwargs: dict = dict(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url="https://clashautoloot.duckdns.org/?paid=subscribe",
        cancel_url="https://clashautoloot.duckdns.org/?cancel=subscribe",
        allow_promotion_codes=True,
    )
    if coupon:
        kwargs["discounts"] = [{"coupon": coupon.strip()}]
        # allow_promotion_codes and discounts are mutually exclusive
        del kwargs["allow_promotion_codes"]

    session = stripe.checkout.Session.create(**kwargs)

    url = session.url
    if not url:
        print("Checkout session has no URL", file=sys.stderr)
        sys.exit(1)

    print(f"Session ID : {session.id}")
    print(f"Price      : {price_id}")
    if coupon:
        print(f"Coupon     : {coupon}  (100% off first month)")
    print()
    print("Open this URL in your browser to complete the test checkout:")
    print(url)
    print()
    print("Then on the VM run:  sudo journalctl -u license-api -f")
    print("Expected log lines:")
    print("  Stripe event received: checkout.session.completed")
    print("  New subscription license CLASH-... issued for <email>")
    print("  Stripe event received: customer.subscription.updated")


if __name__ == "__main__":
    main()
