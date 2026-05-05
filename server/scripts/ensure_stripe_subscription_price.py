"""Idempotently create the Stripe product and $12.00 CAD **one-time** month-extend price.

This is the SKU used by `GET /v1/checkout/month-extend` (quantity = months at checkout).

Run from repo root:
    python -m server.scripts.ensure_stripe_subscription_price

Prints the price_... ID and updates /etc/license-api.env if running as root,
otherwise just prints the value for manual insertion.

You can also set STRIPE_MONTH_EXTEND_PRICE_ID separately; if set, this script only
ensures STRIPE_SUBSCRIPTION_PRICE_ID (legacy env name) matches the one-time price.
"""
from __future__ import annotations

import os
import sys

import stripe

PRODUCT_NAME = "Clash Auto Loot Monthly"
UNIT_AMOUNT = 1200  # cents — $12 CAD per month unit (quantity selects months)
CURRENCY = "cad"
ENV_FILE = "/etc/license-api.env"
ENV_KEY = "STRIPE_SUBSCRIPTION_PRICE_ID"


def main() -> None:
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        try:
            with open(ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("STRIPE_SECRET_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass

    if not api_key:
        print(
            "ERROR: STRIPE_SECRET_KEY not set and not found in /etc/license-api.env",
            file=sys.stderr,
        )
        sys.exit(1)

    stripe.api_key = api_key

    products = stripe.Product.list(active=True, limit=100)
    product_id: str | None = None
    for p in products.auto_paging_iter():
        if p.name == PRODUCT_NAME:
            product_id = p.id
            print(f"Found existing product: {product_id} ({p.name})")
            break

    if product_id is None:
        product = stripe.Product.create(name=PRODUCT_NAME)
        product_id = product.id
        print(f"Created new product: {product_id} ({PRODUCT_NAME})")

    prices = stripe.Price.list(product=product_id, active=True, limit=100)
    price_id: str | None = None
    for pr in prices.auto_paging_iter():
        if pr.unit_amount != UNIT_AMOUNT:
            continue
        if pr.currency != CURRENCY:
            continue
        # One-time SKUs omit recurring entirely.
        recurring = getattr(pr, "recurring", None)
        if recurring is not None:
            continue
        price_id = pr.id
        print(
            f"Found existing one-time price: {price_id} ({UNIT_AMOUNT / 100:.2f} "
            f"{CURRENCY.upper()} × quantity-months)"
        )
        break

    if price_id is None:
        price = stripe.Price.create(
            product=product_id,
            unit_amount=UNIT_AMOUNT,
            currency=CURRENCY,
        )
        price_id = price.id
        print(
            f"Created new one-time price: {price_id} ({UNIT_AMOUNT / 100:.2f} "
            f"{CURRENCY.upper()} × quantity-months)"
        )

    print(f"\n{ENV_KEY}={price_id}")

    try:
        with open(ENV_FILE, "r") as f:
            lines = f.readlines()

        updated = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{ENV_KEY}="):
                new_lines.append(f"{ENV_KEY}={price_id}\n")
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f"{ENV_KEY}={price_id}\n")

        with open(ENV_FILE, "w") as f:
            f.writelines(new_lines)

        print(f"Updated {ENV_FILE} with {ENV_KEY}={price_id}")
    except PermissionError:
        print(f"\nAdd this to /etc/license-api.env manually:\n{ENV_KEY}={price_id}")
    except FileNotFoundError:
        print(f"\nAdd this to /etc/license-api.env manually:\n{ENV_KEY}={price_id}")


if __name__ == "__main__":
    main()
