"""Complete a Hosted Checkout Session in Stripe **test mode** without a browser.

Requires STRIPE_SECRET_KEY and STRIPE_PRICE_ID. Optional SMOKE_CHECKOUT_EMAIL.

Mirrors the Stripe CLI checkout.session.completed fixture (payment_pages confirm).
"""
from __future__ import annotations

import base64
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import stripe

TEST_EMAIL = os.environ.get("SMOKE_CHECKOUT_EMAIL", "jeff.tian23@gmail.com")


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_PRICE_ID")
    if not key or not price_id:
        print("Need STRIPE_SECRET_KEY and STRIPE_PRICE_ID", file=sys.stderr)
        sys.exit(1)
    stripe.api_key = key

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=TEST_EMAIL,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url="https://clashautoloot.duckdns.org/?paid=1",
        cancel_url="https://clashautoloot.duckdns.org/?cancel=1",
    )

    price = stripe.Price.retrieve(price_id)
    unit = price.unit_amount
    if unit is None:
        print("Price has no unit_amount", file=sys.stderr)
        sys.exit(1)
    expected_amount = unit

    pm = stripe.PaymentMethod.create(
        type="card",
        card={"token": "tok_visa"},
        billing_details={"email": TEST_EMAIL, "name": "Smoke Test"},
    )

    auth = base64.b64encode(f"{key}:".encode()).decode()
    body = urllib.parse.urlencode(
        {"payment_method": pm.id, "expected_amount": expected_amount}
    ).encode()

    req = urllib.request.Request(
        f"https://api.stripe.com/v1/payment_pages/{session.id}/confirm",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        sys.exit(1)

    print(f"Checkout session {session.id} confirm OK")
    print(raw[:800])


if __name__ == "__main__":
    main()
