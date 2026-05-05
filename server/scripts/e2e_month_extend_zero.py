"""E2E helper: 100% coupon + zero-total Checkout Session for month-extend SKU.

Run on the license API host with /etc/license-api.env loaded (contains sk_live + price id):

  sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \\
    cd /opt/license-api && .venv/bin/python -m server.scripts.e2e_month_extend_zero'

Outputs checkout URL and session id for Playwright follow-up or manual completion.

With --playwright (optional): tries headless Chromium to complete $0 checkout
(requires: pip install playwright && playwright install chromium).

With --checkout-url URL: only run Playwright completion (no Stripe API calls).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import stripe

PROMO_CODE = "CAL_E2E_ZERO"
COUPON_NAME = "cal_e2e_100_once"
TEST_EMAIL = os.environ.get("E2E_CHECKOUT_EMAIL", "cal-e2e-zero@invalid.example.org")


def _require_env() -> None:
    if not os.environ.get("STRIPE_SECRET_KEY"):
        print("STRIPE_SECRET_KEY missing (source /etc/license-api.env)", file=sys.stderr)
        sys.exit(1)
    price = (os.environ.get("STRIPE_MONTH_EXTEND_PRICE_ID") or "").strip() or (
        os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID") or ""
    ).strip()
    if not price:
        print(
            "STRIPE_SUBSCRIPTION_PRICE_ID or STRIPE_MONTH_EXTEND_PRICE_ID missing",
            file=sys.stderr,
        )
        sys.exit(1)


def ensure_100_percent_coupon() -> str:
    """Return Coupon id with 100% once-off; prefers existing CAL_E2E coupon by name."""
    for c in stripe.Coupon.list(limit=100).auto_paging_iter():
        if getattr(c, "name", None) == COUPON_NAME and getattr(c, "percent_off", None) == 100:
            print(f"reuse coupon {c.id}")
            return c.id
        if getattr(c, "metadata", None) and c.metadata.get("purpose") == "e2e_zero_charge":
            print(f"reuse coupon(by metadata) {c.id}")
            return c.id

    coupon = stripe.Coupon.create(
        percent_off=100,
        duration="once",
        name=COUPON_NAME,
        metadata={"purpose": "e2e_zero_charge"},
    )
    print(f"created Coupon {coupon.id}")
    return coupon.id


def try_create_promotion_code(coupon_id: str) -> None:
    """Optional customer-facing CAL_E2E_ZERO; API version may reject create — safe to skip."""
    try:
        existing = stripe.PromotionCode.list(code=PROMO_CODE, limit=1, active=True)
        if existing.data:
            print(f"reuse PromotionCode {PROMO_CODE} id={existing.data[0].id}")
            return
    except Exception as exc:
        print(f"PromotionCode.list skip: {exc}", file=sys.stderr)

    try:
        promo = stripe.PromotionCode.create(
            coupon=coupon_id,
            code=PROMO_CODE,
            max_redemptions=5,
            active=True,
            metadata={"purpose": "e2e_zero_charge"},
        )
        print(f"created PromotionCode {promo.code} id={promo.id}")
    except Exception as exc:
        print(
            "PromotionCode.create skipped (%s); use Dashboard promo or rely on embedded coupon discount."
            % (exc,),
            file=sys.stderr,
        )


_CUSTOM_FIELDS = [
    {
        "key": "existing_license_key",
        "label": {
            "type": "custom",
            "custom": "Existing license key (leave blank for a new key)",
        },
        "type": "text",
        "optional": True,
    },
]


def create_zero_session(price_id: str, coupon_id: str) -> stripe.checkout.Session:
    return stripe.checkout.Session.create(
        mode="payment",
        customer_email=TEST_EMAIL,
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
                "adjustable_quantity": {"enabled": True, "minimum": 1, "maximum": 36},
            }
        ],
        discounts=[{"coupon": coupon_id}],
        custom_fields=_CUSTOM_FIELDS,
        success_url="https://clashautoloot.duckdns.org/?paid=extend&e2e=1",
        cancel_url="https://clashautoloot.duckdns.org/?cancel=extend&e2e=1",
    )


def playwright_complete(url: str, *, headed: bool = False) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed; pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = ctx.new_page()
        page.set_default_timeout(120_000)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except Exception as exc:
            print(f"page.goto failed: {exc}", file=sys.stderr)
            ctx.close()
            browser.close()
            return False

        time.sleep(3)

        filled = False
        for frame in page.frames:
            try:
                inp = frame.locator(
                    'input[type="email"], input#email, input[name="email"], input[autocomplete="email"]'
                )
                if inp.count():
                    inp.first.fill(TEST_EMAIL)
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            print("email fill failed: no email input in main page or iframes", file=sys.stderr)
            ctx.close()
            browser.close()
            return False

        time.sleep(1)
        clicked = False
        for frame in page.frames:
            for name in ("Pay", "Complete order", "Subscribe", "Continue"):
                try:
                    btn = frame.get_by_role("button", name=name)
                    if btn.count() and btn.first.is_enabled():
                        btn.first.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break
        if not clicked:
            for frame in page.frames:
                try:
                    sub = frame.locator('button[data-testid="hosted-payment-submit-button"]')
                    if sub.count():
                        sub.first.click()
                        clicked = True
                        break
                except Exception:
                    continue

        try:
            page.wait_for_url("**/clashautoloot.duckdns.org/**", timeout=120_000)
        except Exception as exc:
            print(f"wait_for_url: {exc}", file=sys.stderr)
            ctx.close()
            browser.close()
            return False
        ctx.close()
        browser.close()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="Try headless browser to complete $0 checkout",
    )
    parser.add_argument(
        "--checkout-url",
        default="",
        help="Only run Playwright against this Checkout URL (skip Session.create)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Non-headless browser (may help if Stripe blocks headless automation)",
    )
    args = parser.parse_args()

    if args.checkout_url:
        if not args.playwright:
            print("--checkout-url requires --playwright", file=sys.stderr)
            sys.exit(1)
        ok = playwright_complete(args.checkout_url.strip(), headed=args.headed)
        print(f"playwright_complete\t{ok}")
        sys.exit(0 if ok else 1)

    _require_env()
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

    price_id = (os.environ.get("STRIPE_MONTH_EXTEND_PRICE_ID") or "").strip() or os.environ[
        "STRIPE_SUBSCRIPTION_PRICE_ID"
    ].strip()

    coupon_id = ensure_100_percent_coupon()
    try_create_promotion_code(coupon_id)

    sess = create_zero_session(price_id, coupon_id)
    sess2 = stripe.checkout.Session.retrieve(sess.id)
    url = sess2.url or sess.url
    print(f"session_id\t{sess2.id}")
    print(f"amount_total\t{sess2.amount_total}")
    print(f"url\t{url}")

    if not url:
        sys.exit(1)

    if args.playwright:
        ok = playwright_complete(url, headed=args.headed)
        print(f"playwright_complete\t{ok}")
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
