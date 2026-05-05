"""Create a Payment Link for STRIPE_SUBSCRIPTION_PRICE_ID (optional utility).

Stripe Payment Links cannot reproduce Checkout `custom_fields` (existing license key)
and adjustable_quantity the way the `/v1/checkout/month-extend` redirect does.
Prefer deploying the FastAPI redirect for month purchases so the webhook can
extend billing correctly.

Still useful if you temporarily need a dumb link:

    set STRIPE_SECRET_KEY=sk_...
    set STRIPE_SUBSCRIPTION_PRICE_ID=price_...
    python -m server.scripts.create_subscription_payment_link
"""
from __future__ import annotations

import os
import sys

import stripe


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    price_id = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID", "").strip()
    if not key or not price_id:
        print("Need STRIPE_SECRET_KEY and STRIPE_SUBSCRIPTION_PRICE_ID", file=sys.stderr)
        sys.exit(1)
    stripe.api_key = key
    pl = stripe.PaymentLink.create(line_items=[{"price": price_id, "quantity": 1}])
    url = pl.url
    if not url:
        print("PaymentLink has no URL", file=sys.stderr)
        sys.exit(1)
    print(url)


if __name__ == "__main__":
    main()
