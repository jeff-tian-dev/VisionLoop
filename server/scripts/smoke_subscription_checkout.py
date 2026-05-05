"""Create a test Checkout Session mirroring `/v1/checkout/month-extend` (browser flow).

Requires STRIPE_SECRET_KEY and STRIPE_SUBSCRIPTION_PRICE_ID (one-time CAD price;
see `ensure_stripe_subscription_price`).

Uses mode=payment, adjustable_quantity (months), optional custom_fields for testing.

Does not complete payment automatically.

Run:
    set STRIPE_SECRET_KEY=sk_test_...
    set STRIPE_SUBSCRIPTION_PRICE_ID=price_...
    python -m server.scripts.smoke_subscription_checkout

Open the printed URL, pay with test card 4242..., webhook should claim
`stripe_checkout_fulfillments` then mint NEW timed rows or PATCH existing keys.
"""
from __future__ import annotations

import os
import sys

import stripe

TEST_EMAIL = os.environ.get("SMOKE_CHECKOUT_EMAIL", "test@example.com")


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID")
    if not key or not price_id:
        print("Need STRIPE_SECRET_KEY and STRIPE_SUBSCRIPTION_PRICE_ID", file=sys.stderr)
        sys.exit(1)
    stripe.api_key = key

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=TEST_EMAIL,
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
                "label": {"type": "custom", "custom": "Existing license key (leave blank for a new key)"},
                "type": "text",
                "optional": True,
            },
        ],
        success_url="https://clashautoloot.duckdns.org/?paid=extend",
        cancel_url="https://clashautoloot.duckdns.org/?cancel=extend",
    )
    url = session.url
    if not url:
        print("Checkout session has no URL", file=sys.stderr)
        sys.exit(1)
    print(f"Session: {session.id}")
    print(f"Open in browser:\n{url}")


if __name__ == "__main__":
    main()
