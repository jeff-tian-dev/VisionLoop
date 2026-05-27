"""Replay a missed checkout.session.completed event through the local webhook handler.

Usage (on VM as root):
    sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \
      cd /opt/license-api && /opt/license-api/.venv/bin/python -m server.scripts.replay_checkout \
      cs_live_b12gbF2IlXW8jJOk6AhPLSTkd5MnrHCbupVD7HXcG2ptXHHOeyrVf9ANbB'
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import stripe

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not session_id:
        print("Usage: replay_checkout.py <checkout_session_id>", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not api_key:
        print("STRIPE_SECRET_KEY not set", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = api_key

    from server.db import init_pool, close_pool
    from server.stripe_webhook import handle_checkout_completed, _event_object_to_dict

    await init_pool()
    try:
        print(f"Fetching session {session_id} ...")
        session = stripe.checkout.Session.retrieve(session_id, expand=["line_items.data.price"])
        raw = _event_object_to_dict(session)
        mode = raw.get("mode")
        print(f"Mode: {mode}  Status: {raw.get('status')}  Customer: {raw.get('customer')}")

        print("Replaying handle_checkout_completed ...")
        await handle_checkout_completed(raw)
        print("Done.")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
