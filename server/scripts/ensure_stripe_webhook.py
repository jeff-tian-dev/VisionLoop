"""Create or refresh the Stripe webhook endpoint for license + subscription events.

Stripe only returns the signing secret when an endpoint is created. If an endpoint
already exists for our URL, it is deleted and recreated so /etc/license-api.env can
receive a fresh STRIPE_WEBHOOK_SECRET.

Run on the VM (as root so the env file can be updated):

    sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \\
      cd /opt/license-api && /opt/license-api/.venv/bin/python -m server.scripts.ensure_stripe_webhook'
"""
from __future__ import annotations

import os
import subprocess
import sys

import stripe

WEBHOOK_URL = "https://clashautoloot.duckdns.org/v1/stripe/webhook"
ENV_FILE = "/etc/license-api.env"


def _load_stripe_key() -> str:
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if api_key:
        return api_key.strip()
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("STRIPE_SECRET_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    print("ERROR: STRIPE_SECRET_KEY not set and not found in /etc/license-api.env", file=sys.stderr)
    sys.exit(1)


def _restore_selinux_env_label() -> None:
    if os.geteuid() != 0:
        return
    try:
        subprocess.run(
            ["chcon", "system_u:object_r:etc_t:s0", ENV_FILE],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def _patch_env(webhook_secret: str) -> None:
    with open(ENV_FILE) as f:
        lines = f.readlines()

    new_lines: list[str] = []
    updated = False
    for line in lines:
        if line.startswith("STRIPE_WEBHOOK_SECRET="):
            new_lines.append(f"STRIPE_WEBHOOK_SECRET={webhook_secret}\n")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"STRIPE_WEBHOOK_SECRET={webhook_secret}\n")

    with open(ENV_FILE, "w") as f:
        f.writelines(new_lines)


def main() -> None:
    stripe.api_key = _load_stripe_key()

    removed = 0
    for we in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter():
        if we.url == WEBHOOK_URL:
            stripe.WebhookEndpoint.delete(we.id)
            removed += 1

    if removed:
        print(f"Removed {removed} existing endpoint(s) for {WEBHOOK_URL}")

    created = stripe.WebhookEndpoint.create(
        url=WEBHOOK_URL,
        enabled_events=[
            "checkout.session.completed",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ],
    )
    secret = created.secret
    if not secret:
        print("ERROR: Stripe did not return a signing secret", file=sys.stderr)
        sys.exit(1)

    print(f"Registered webhook endpoint {created.id} → {WEBHOOK_URL}")

    try:
        _patch_env(secret)
        _restore_selinux_env_label()
        print(f"Updated {ENV_FILE} with STRIPE_WEBHOOK_SECRET (value not printed).")
    except PermissionError:
        print(
            "\nCould not write env file. Add manually:\nSTRIPE_WEBHOOK_SECRET=<from Stripe Dashboard>",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
