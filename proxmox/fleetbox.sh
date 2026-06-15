#!/usr/bin/env bash
#
# FleetBox — Proxmox VE LXC installer
# -----------------------------------
# Run this ON THE PROXMOX HOST. It creates a Debian 12 LXC container and
# installs FleetBox as a systemd service.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/skyhell/fleetbox/main/proxmox/fleetbox.sh)"
#
# Configurable via environment variables (all optional):
#   CTID, HOSTNAME, DISK_GB, CORES, RAM_MB, BRIDGE, STORAGE, TEMPLATE,
#   REPO_URL, REPO_BRANCH, FLEETBOX_PORT
#
set -euo pipefail

# ---- Defaults --------------------------------------------------------------
CTID="${CTID:-}"
HOSTNAME="${HOSTNAME:-fleetbox}"
DISK_GB="${DISK_GB:-4}"
CORES="${CORES:-1}"
RAM_MB="${RAM_MB:-512}"
BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
TEMPLATE="${TEMPLATE:-debian-12-standard}"
REPO_URL="${REPO_URL:-https://github.com/skyhell/fleetbox.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
FLEETBOX_PORT="${FLEETBOX_PORT:-8000}"

msg()  { echo -e "\e[1;32m[+]\e[0m $*"; }
warn() { echo -e "\e[1;33m[!]\e[0m $*"; }
die()  { echo -e "\e[1;31m[x]\e[0m $*" >&2; exit 1; }

command -v pct >/dev/null 2>&1 || die "This script must run on a Proxmox VE host (pct not found)."

# ---- Pick a free container ID ---------------------------------------------
if [[ -z "$CTID" ]]; then
  CTID=$(pvesh get /cluster/nextid)
fi
msg "Using container ID: $CTID"

# ---- Ensure the LXC template is available ---------------------------------
msg "Updating template catalog..."
pveam update >/dev/null 2>&1 || true
TEMPLATE_FILE=$(pveam available --section system | awk '{print $2}' | grep "^${TEMPLATE}" | sort -V | tail -n1 || true)
[[ -n "$TEMPLATE_FILE" ]] || die "Template matching '$TEMPLATE' not found in the catalog."

if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE_FILE"; then
  msg "Downloading template $TEMPLATE_FILE ..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_FILE"
fi
TEMPLATE_REF="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE_FILE}"

# ---- Create the container --------------------------------------------------
msg "Creating LXC container '$HOSTNAME' ($CTID)..."
pct create "$CTID" "$TEMPLATE_REF" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" \
  --memory "$RAM_MB" \
  --rootfs "${STORAGE}:${DISK_GB}" \
  --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
  --features nesting=1 \
  --unprivileged 1 \
  --onboot 1

msg "Starting container..."
pct start "$CTID"
sleep 5

# ---- Provision inside the container ---------------------------------------
msg "Installing dependencies inside the container..."
pct exec "$CTID" -- bash -euo pipefail -c "
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3 python3-venv python3-pip ca-certificates >/dev/null
"

msg "Cloning FleetBox ($REPO_BRANCH)..."
pct exec "$CTID" -- bash -euo pipefail -c "
  rm -rf /opt/fleetbox
  git clone --depth 1 --branch '$REPO_BRANCH' '$REPO_URL' /opt/fleetbox
  python3 -m venv /opt/fleetbox/.venv
  /opt/fleetbox/.venv/bin/pip install --quiet --upgrade pip
  /opt/fleetbox/.venv/bin/pip install --quiet -r /opt/fleetbox/requirements.txt
"

msg "Generating configuration..."
SECRET=$(pct exec "$CTID" -- python3 -c "import secrets; print(secrets.token_urlsafe(48))")
pct exec "$CTID" -- bash -euo pipefail -c "
  mkdir -p /opt/fleetbox/data
  cat > /opt/fleetbox/.env <<EOF
FLEETBOX_SECRET_KEY=${SECRET}
FLEETBOX_DATABASE_URL=sqlite:////opt/fleetbox/data/fleetbox.db
FLEETBOX_HOST=0.0.0.0
FLEETBOX_PORT=${FLEETBOX_PORT}
FLEETBOX_DEFAULT_LOCALE=de
FLEETBOX_ALLOW_REGISTRATION=true
# Set to true when serving over HTTPS behind a reverse proxy (nginx/Caddy):
FLEETBOX_SECURE_COOKIES=false
# Trusted reverse-proxy IP(s) for X-Forwarded-* headers (comma-separated, or *).
# Set this to your nginx host's IP for stricter security.
FLEETBOX_FORWARDED_ALLOW_IPS=127.0.0.1
EOF
  /opt/fleetbox/.venv/bin/python -m app.cli init-db >/dev/null 2>&1 || \
    (cd /opt/fleetbox && /opt/fleetbox/.venv/bin/python -m app.cli init-db)
"

msg "Creating dedicated service user..."
pct exec "$CTID" -- bash -euo pipefail -c "
  id fleetbox >/dev/null 2>&1 || useradd --system --home-dir /opt/fleetbox --shell /usr/sbin/nologin fleetbox
  chown -R fleetbox:fleetbox /opt/fleetbox
"

msg "Installing systemd service..."
pct exec "$CTID" -- bash -euo pipefail -c "
  cat > /etc/systemd/system/fleetbox.service <<'EOF'
[Unit]
Description=FleetBox vehicle management
After=network.target

[Service]
Type=simple
User=fleetbox
Group=fleetbox
WorkingDirectory=/opt/fleetbox
EnvironmentFile=/opt/fleetbox/.env
ExecStart=/opt/fleetbox/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \${FLEETBOX_PORT} --proxy-headers --forwarded-allow-ips=\${FLEETBOX_FORWARDED_ALLOW_IPS}
Restart=on-failure
RestartSec=5

# --- Sandboxing / hardening ---
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
ReadWritePaths=/opt/fleetbox/data

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now fleetbox.service
"

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
msg "Done!"
echo
echo "  FleetBox is running in container $CTID."
echo "  Open:  http://${IP}:${FLEETBOX_PORT}"
echo
echo "  The first account you register becomes the administrator."
echo "  Logs:  pct exec $CTID -- journalctl -u fleetbox -f"
