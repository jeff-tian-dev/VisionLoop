# Clash Auto Loot – License API Operator Runbook

## Overview

| Component | Location |
|-----------|----------|
| FastAPI service | `/opt/license-api/` on Oracle Cloud VM |
| systemd unit | `license-api.service` |
| Credentials | `/etc/license-api.env` (mode 600, owner `licapi`) |
| Logs | `journalctl -u license-api -f` |
| Caddy logs | `/var/log/caddy/access.log` |
| Public URL | `https://clashautoloot.duckdns.org` |

---

## Supabase migrations

Apply SQL files under `server/migrations/` to your Supabase project (SQL editor or your migration tool) **in numeric order**. Through **`0005`**: subscription columns + `validate_license` expiry check. **`0006`**: successful validation JSON also includes **`expires_at`** (for the desktop UI). **`0008`**: **`stripe_checkout_fulfillments`** idempotency table for Stripe webhooks (required for monthly extend Checkout).

---

## Initial Deploy

### Prerequisites

1. **OCI Security List** — add stateful ingress for TCP 80 and 443 from `0.0.0.0/0` in the OCI console:
   - https://cloud.oracle.com → Networking → Virtual Cloud Networks → VCN → Security Lists → public subnet list → Add Ingress Rules
   - Source CIDR: `0.0.0.0/0`, Protocol: TCP, Destination Port: `80`, and again for `443`

2. **DuckDNS** — subdomain `clashautoloot` must exist at https://duckdns.org pointing at the VM's public IP `147.5.112.162`.

3. **SSH access** — confirm `ssh -i SSH_VMKEY.key opc@147.5.112.162` works.

### Run from developer machine (Windows)

```powershell
# 1. Write the env file (never commit this)
$env = @"
ENV=prod
PORT=8000
DUCKDNS_SUBDOMAIN=clashautoloot
DUCKDNS_TOKEN=<your-token>
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<your-anon-jwt>
STRIPE_SECRET_KEY=<sk_test_or_live_...>
STRIPE_PRICE_ID=<price_...>
# One-time $12 CAD / month-unit (checkout quantity = months). Legacy name retained for VM churn:
STRIPE_SUBSCRIPTION_PRICE_ID=<price_one_time_extend_...>
# Optional clearer override (if set, used instead of STRIPE_SUBSCRIPTION_PRICE_ID for extend):
STRIPE_MONTH_EXTEND_PRICE_ID=
STRIPE_WEBHOOK_SECRET=
RESEND_API_KEY=<re_...>
RESEND_DOMAIN=clashautoloot.com
EMAIL_FROM=Clash Auto Loot <licenses@clashautoloot.com>
SUPPORT_EMAIL=clashautoloot@gmail.com
"@

# 2. Copy server code to VM
scp -i C:\Projects\Clash_Auto_Loot\SSH_VMKEY.key -r C:\Projects\Clash_Auto_Loot\server\* opc@147.5.112.162:/tmp/license-api-src/

# 3. On VM: move files, write env, run install.sh
ssh -i C:\Projects\Clash_Auto_Loot\SSH_VMKEY.key opc@147.5.112.162 "sudo mkdir -p /opt/license-api && sudo rsync -av /tmp/license-api-src/ /opt/license-api/"
ssh -i C:\Projects\Clash_Auto_Loot\SSH_VMKEY.key opc@147.5.112.162 "sudo bash /opt/license-api/deploy/install.sh"

# 4. Create Stripe product/prices: one-time lifetime + one-time monthly unit ($12 CAD × quantity months)
ssh -i C:\Projects\Clash_Auto_Loot\SSH_VMKEY.key opc@147.5.112.162 "sudo /opt/license-api/.venv/bin/python -m server.scripts.ensure_stripe_price"
ssh -i C:\Projects\Clash_Auto_Loot\SSH_VMKEY.key opc@147.5.112.162 "sudo /opt/license-api/.venv/bin/python -m server.scripts.ensure_stripe_subscription_price"

# 5. Smoke test
curl.exe https://clashautoloot.duckdns.org/v1/health
```

---

## Stripe Webhook Setup (do after first deploy)

1. Go to https://dashboard.stripe.com/test/webhooks → Add endpoint
2. URL: `https://clashautoloot.duckdns.org/v1/stripe/webhook`
3. Events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
4. Copy the signing secret (`whsec_...`)
5. Add to `/etc/license-api.env` on the VM:
   ```bash
   sudo nano /etc/license-api.env
   # Set STRIPE_WEBHOOK_SECRET=whsec_...
   sudo systemctl restart license-api
   ```

   **Alternative:** on the VM, recreate the endpoint and patch the env file (rewrites `STRIPE_WEBHOOK_SECRET`):

   ```bash
   sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \
     cd /opt/license-api && /opt/license-api/.venv/bin/python -m server.scripts.ensure_stripe_webhook'
   ```

6. Test: complete a test checkout or use "Send test event" in the Stripe dashboard. Expect a row in **`stripe_checkout_fulfillments`** for lifetime / month-bundle checkouts plus updates to **`licenses`** (new timed keys, PATCHed `expires_at` on extend). Legacy Stripe **subscriptions** still write `stripe_subscription_id` until fully retired.

For month-bundle checkout in test mode without the public redirect URL, print a Stripe Checkout URL locally:

`/opt/license-api/.venv/bin/python -m server.scripts.smoke_subscription_checkout` (requires `STRIPE_SUBSCRIPTION_PRICE_ID` pointing at the **one-time** extend price).

### Desktop app: month extend checkout

The app opens **`GET https://clashautoloot.duckdns.org/v1/checkout/month-extend`**, which creates a server-side Stripe Checkout Session (`STRIPE_SECRET_KEY` stays on the VM): adjustable quantity for months plus an optional “existing license key” field. Static **Payment Links** cannot supply that UX—do not swap in a naked buy link unless you drop extend support for that funnel.

Customers can bookmark the same DuckDNS URL; rate limits apply.

## Daily Operations

### Issue a key manually

```bash
cd /opt/license-api
sudo -u licapi .venv/bin/python -m server.admin_cli issue --email customer@example.com
```

### Revoke a key

```bash
sudo -u licapi .venv/bin/python -m server.admin_cli revoke CLASH-XXXX-XXXX-XXXX-XXXX --notes "reason"
```

### Look up a key or customer

```bash
sudo -u licapi .venv/bin/python -m server.admin_cli lookup --email customer@example.com
sudo -u licapi .venv/bin/python -m server.admin_cli lookup --key CLASH-XXXX-XXXX-XXXX-XXXX
```

### Transfer a key to a new machine (reset hardware binding)

```bash
sudo -u licapi .venv/bin/python -m server.admin_cli reset-machine CLASH-XXXX-XXXX-XXXX-XXXX
```

The next time the customer activates on any machine, that machine becomes the new bound machine.

---

## Updating the Server

```powershell
# From Windows dev machine
scp -i SSH_VMKEY.key -r server\* opc@147.5.112.162:/tmp/license-api-src/
ssh -i SSH_VMKEY.key opc@147.5.112.162 "sudo rsync -av --exclude='.venv' /tmp/license-api-src/ /opt/license-api/ && sudo systemctl restart license-api"
```

---

## Rotating Credentials

Edit `/etc/license-api.env` on the VM, then `sudo systemctl restart license-api`.

To rotate the Resend API key:
1. Generate a new key in https://resend.com/api-keys
2. Update `RESEND_API_KEY` in `/etc/license-api.env`
3. `sudo systemctl restart license-api`

---

## Before Going Live (checklist)

- [ ] Switch `STRIPE_SECRET_KEY` from `sk_test_...` to `sk_live_...`
- [ ] Switch `STRIPE_PRICE_ID` to the live mode one-time Price ID (re-run `ensure_stripe_price.py`)
- [ ] Switch `STRIPE_SUBSCRIPTION_PRICE_ID` (or `STRIPE_MONTH_EXTEND_PRICE_ID`) to the live **one-time** month-unit Price ID (re-run `ensure_stripe_subscription_price.py`)
- [ ] Register a new Stripe webhook for live mode (same three events) and update `STRIPE_WEBHOOK_SECRET`
- [ ] Verify Resend sending domain `clashautoloot.com` is green in Resend dashboard
- [ ] Update `EMAIL_FROM` to the real sending address if needed
- [ ] `sudo systemctl restart license-api`

---

## Logs & Troubleshooting

```bash
# API logs (live)
journalctl -u license-api -f

# Last 100 lines
journalctl -u license-api -n 100

# Caddy access log
tail -f /var/log/caddy/access.log

# DuckDNS timer status
systemctl status duckdns-update.timer
journalctl -u duckdns-update.service -n 20

# Check Supabase REST from VM (same path the API uses)
sudo bash -lc 'set -a; source /etc/license-api.env; set +a; \
  curl -sS -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
  "$SUPABASE_URL/rest/v1/licenses?select=id&limit=1"'
```
