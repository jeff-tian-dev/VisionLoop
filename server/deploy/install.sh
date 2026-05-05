#!/usr/bin/env bash
# install.sh — Idempotent deploy for Clash Auto Loot license API (Oracle Linux 9)
#
# Layout on VM:
#   /opt/license-api/server/     Python package + deploy/*.service + requirements.txt
#   /opt/license-api/.venv/      Virtualenv
#
# Credentials: /etc/license-api.env (written separately; owner root / licapi-readable via EnvironmentFile)

set -euo pipefail

APP_ROOT="/opt/license-api"
CODE_DIR="$APP_ROOT/server"
VENV="$APP_ROOT/.venv"
SERVICE_DIR="/etc/systemd/system"

log() { echo "[install.sh] $*"; }

# ─── 1. System packages (split installs — avoids OOM on 1 GiB VMs) ─────────────
log "Installing git..."
dnf install -y git

log "Installing Python 3.12..."
dnf install -y python3.12 python3.12-pip

if ! command -v caddy &>/dev/null; then
    log "Adding Caddy Cloudsmith repo..."
    cat > /etc/yum.repos.d/caddy.repo <<'EOF'
[caddy]
name=Caddy
baseurl=https://dl.cloudsmith.io/public/caddy/stable/rpm/el/$releasever/$basearch/
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://dl.cloudsmith.io/public/caddy/stable/gpg.key
       https://dl.cloudsmith.io/public/caddy/stable/gpg.key
enabled=1
EOF
fi

log "Installing Caddy..."
dnf install -y caddy

log "Ensuring curl / rsync..."
dnf install -y curl rsync

# ─── 2. User & permissions ────────────────────────────────────────────────────
log "Setting up licapi user..."
if ! id licapi &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin licapi
fi
chown -R licapi:licapi "$APP_ROOT"

# ─── 3. Python venv ─────────────────────────────────────────────────────────────
log "Setting up Python venv..."
if [ ! -d "$VENV" ]; then
    python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$CODE_DIR/requirements.txt"
chown -R licapi:licapi "$VENV"

# ─── 4. license-api systemd ─────────────────────────────────────────────────────
log "Installing license-api.service..."
cp "$CODE_DIR/deploy/license-api.service" "$SERVICE_DIR/license-api.service"
systemctl daemon-reload
systemctl enable license-api
systemctl restart license-api || true
log "license-api status: $(systemctl is-active license-api || echo inactive)"

# ─── 5. Caddy ─────────────────────────────────────────────────────────────────
log "Configuring Caddy..."
mkdir -p /etc/caddy /var/log/caddy
cp "$CODE_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
chown caddy:caddy /var/log/caddy 2>/dev/null || true
systemctl enable caddy
systemctl restart caddy || true
log "caddy status: $(systemctl is-active caddy || echo inactive)"

# ─── 6. DuckDNS ────────────────────────────────────────────────────────────────
log "Installing DuckDNS timer..."
cp "$CODE_DIR/deploy/duckdns-update.service" "$SERVICE_DIR/duckdns-update.service"
cp "$CODE_DIR/deploy/duckdns-update.timer" "$SERVICE_DIR/duckdns-update.timer"
systemctl daemon-reload
systemctl enable duckdns-update.timer
systemctl start duckdns-update.timer || true
systemctl start duckdns-update.service || true

# ─── 7. Firewall ──────────────────────────────────────────────────────────────
log "Opening firewall ports 80 / 443..."
firewall-cmd --add-service=http --permanent 2>/dev/null || true
firewall-cmd --add-service=https --permanent 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true

log "Done."
log "Smoke test (localhost): curl -s http://127.0.0.1:8000/v1/health"
curl -sf http://127.0.0.1:8000/v1/health && echo "" || log "WARNING: license-api health failed — journalctl -u license-api -n 80"
