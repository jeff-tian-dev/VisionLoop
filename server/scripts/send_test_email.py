"""Send a test license email to verify the HTML template.

Usage (on VM):
    sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \
      cd /opt/license-api && /opt/license-api/.venv/bin/python -m server.scripts.send_test_email \
      jeff.tian23@gmail.com'
"""
from __future__ import annotations

import asyncio
import sys

from server.db import init_pool, close_pool
from server.email_client import send_license_email


async def main() -> None:
    to = sys.argv[1] if len(sys.argv) > 1 else "jeff.tian23@gmail.com"
    await init_pool()
    try:
        await send_license_email(
            to,
            "CLASH-TEST-PREVIEW-KEY-0001",
            fulfillment_type="subscription",
            expires_at_iso="2026-06-27T19:30:00+00:00",
        )
        print(f"Test email sent to {to}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
