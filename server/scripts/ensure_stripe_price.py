"""Idempotently create the Stripe product and $99.00 CAD one-time (lifetime) price.

Run from repo root:
    python -m server.scripts.ensure_stripe_price

Prints the price_... ID and updates /etc/license-api.env if running as root,
otherwise just prints the value for manual insertion.
"""
from __future__ import annotations

import os
import sys

import stripe

PRODUCT_NAME = "Clash Auto Loot License"
UNIT_AMOUNT = 9900   # cents ($99.00 CAD lifetime)
CURRENCY = "cad"
ENV_FILE = "/etc/license-api.env"


def main() -> None:
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        # Try loading from env file
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
        print("ERROR: STRIPE_SECRET_KEY not set and not found in /etc/license-api.env", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = api_key

    # --- Find or create product ---
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

    # --- Find or create price ---
    prices = stripe.Price.list(product=product_id, active=True, limit=100)
    price_id: str | None = None
    for pr in prices.auto_paging_iter():
        if (
            pr.unit_amount == UNIT_AMOUNT
            and pr.currency == CURRENCY
            and pr.recurring is None
        ):
            price_id = pr.id
            print(f"Found existing price: {price_id} ({UNIT_AMOUNT/100:.2f} {CURRENCY.upper()})")
            break

    if price_id is None:
        price = stripe.Price.create(
            product=product_id,
            unit_amount=UNIT_AMOUNT,
            currency=CURRENCY,
        )
        price_id = price.id
        print(f"Created new price: {price_id} ({UNIT_AMOUNT/100:.2f} {CURRENCY.upper()})")

    print(f"\nSTRIPE_PRICE_ID={price_id}")

    # --- Update env file if writable ---
    try:
        with open(ENV_FILE, "r") as f:
            lines = f.readlines()

        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("STRIPE_PRICE_ID="):
                new_lines.append(f"STRIPE_PRICE_ID={price_id}\n")
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f"STRIPE_PRICE_ID={price_id}\n")

        with open(ENV_FILE, "w") as f:
            f.writelines(new_lines)

        print(f"Updated {ENV_FILE} with STRIPE_PRICE_ID={price_id}")
    except PermissionError:
        print(f"\nAdd this to /etc/license-api.env manually:\nSTRIPE_PRICE_ID={price_id}")
    except FileNotFoundError:
        print(f"\nAdd this to /etc/license-api.env manually:\nSTRIPE_PRICE_ID={price_id}")


if __name__ == "__main__":
    main()
