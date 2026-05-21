"""Create 100%-off coupon + promo, lifetime Checkout for \$0 CAD, Payment Page confirm.

Requires ``STRIPE_SECRET_KEY`` and ``STRIPE_PRICE_ID``. The Price id **must match**
``STRIPE_PRICE_ID`` on the license API VM or webhooks skip fulfillment (“no configured
price id matched line items”).

Optional ``SMOKE_CHECKOUT_EMAIL`` (default ``jeff.tian23@gmail.com``).

100% Stripe Coupon ``cal_lifetime_100_once`` is created/reused automatically. Stripe’s
PromotionCode API rejected programmatic creation here; link promo code ``CAL_LIFETIME_FREE100``
to that coupon in the Dashboard if you need a customer-visible code—the Checkout Session
already applies the 100%% coupon via embedded ``discounts``.

Live \$0 confirms use ``customer_data`` + ``expected_amount`` 0 (no test PM). Test mode
still adds ``tok_visa`` when ``sk_test`` is detected.
"""
from __future__ import annotations

import base64
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import stripe

PROMO_CODE = "CAL_LIFETIME_FREE100"
COUPON_NAME = "cal_lifetime_100_once"
TEST_EMAIL = os.environ.get("SMOKE_CHECKOUT_EMAIL", "jeff.tian23@gmail.com")


def _ensure_100_coupon() -> str:
    for c in stripe.Coupon.list(limit=100).auto_paging_iter():
        if getattr(c, "name", None) == COUPON_NAME and getattr(c, "percent_off", None) == 100:
            print(f"reuse coupon {c.id}")
            return c.id
        md = getattr(c, "metadata", None)
        purpose = None
        if md is not None:
            try:
                purpose = md["purpose"]
            except (KeyError, TypeError):
                pass
        if purpose == "lifetime_smoke_100":
            print(f"reuse coupon (metadata) {c.id}")
            return c.id
    new_c = stripe.Coupon.create(
        percent_off=100,
        duration="once",
        name=COUPON_NAME,
        metadata={"purpose": "lifetime_smoke_100"},
    )
    print(f"created coupon {new_c.id}")
    return new_c.id


def _ensure_promo(coupon_id: str) -> None:
    try:
        existing = stripe.PromotionCode.list(code=PROMO_CODE, limit=1, active=True)
        if existing.data:
            print(f"reuse promo {PROMO_CODE} -> {existing.data[0].id}")
            return
    except Exception as exc:
        print(f"PromotionCode.list: {exc}", file=sys.stderr)

    try:
        promo = stripe.PromotionCode.create(
            coupon=coupon_id,
            code=PROMO_CODE,
            max_redemptions=20,
            active=True,
            metadata={"purpose": "lifetime_smoke_100"},
        )
        print(f"created promo {PROMO_CODE} id={promo.id}")
    except Exception as exc:
        print(
            f"PromotionCode.create failed ({exc}); checkout still uses embedded 100% coupon. "
            f"Add promo code {PROMO_CODE} manually in Stripe Dashboard if needed.",
            file=sys.stderr,
        )


def _confirm(session_id: str, expected_amount: int, email: str) -> None:
    key = stripe.api_key or ""
    auth = base64.b64encode(f"{key}:".encode()).decode()
    pairs: list[tuple[str, str]] = [
        ("expected_amount", str(expected_amount)),
        ("customer_data[email]", email),
        ("customer_data[name]", "Promo Smoke Test"),
    ]
    # Test mode can complete with tok_visa; live $0 checkout must not use test tokens.
    if expected_amount == 0 and (key or "").startswith("sk_test"):
        pm = stripe.PaymentMethod.create(
            type="card",
            card={"token": "tok_visa"},
            billing_details={"email": email, "name": "Promo Smoke Test"},
        )
        pairs.append(("payment_method", pm.id))

    body = urllib.parse.urlencode(pairs).encode()
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/payment_pages/{session_id}/confirm",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=90)
        print(resp.read().decode()[:1200])
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        raise


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = (os.environ.get("STRIPE_PRICE_ID") or "").strip()
    if not key or not price_id:
        print("Need STRIPE_SECRET_KEY and STRIPE_PRICE_ID", file=sys.stderr)
        sys.exit(1)
    stripe.api_key = key

    coupon_id = _ensure_100_coupon()
    _ensure_promo(coupon_id)

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=TEST_EMAIL,
        line_items=[{"price": price_id, "quantity": 1}],
        discounts=[{"coupon": coupon_id}],
        success_url="https://clashautoloot.duckdns.org/?paid=lifetime&smoke=1",
        cancel_url="https://clashautoloot.duckdns.org/?cancel=lifetime&smoke=1",
    )
    sess = stripe.checkout.Session.retrieve(session.id)
    total = sess.amount_total
    if total is None:
        print("session has no amount_total", file=sys.stderr)
        sys.exit(1)
    print(f"session_id\t{sess.id}")
    print(f"amount_total\t{total}")
    print(f"promo_code\t{PROMO_CODE} (customer can enter or discount pre-applied via coupon in session)")
    _confirm(sess.id, int(total), TEST_EMAIL)
    print("confirm OK — webhook should mint license shortly")


if __name__ == "__main__":
    main()
