#!/usr/bin/env bash
#
# FleetBox provisioning script (no Git required)
# ----------------------------------------------
# Run this INSIDE the target machine (a Proxmox LXC, a Debian/Ubuntu VM or any
# bare-metal Debian box) where the FleetBox source has already been copied to
# INSTALL_DIR. It sets up the virtualenv, configuration, database and a systemd
# service.
#
#   sudo INSTALL_DIR=/opt/fleetbox bash scripts/install.sh
#
# Configurable via environment variables (all optional):
#   INSTALL_DIR, FLEETBOX_PORT, FLEETBOX_DEFAULT_LOCALE, FLEETBOX_ALLOW_REGISTRATION
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/fleetbox}"
SERVICE_USER="${SERVICE_USER:-fleetbox}"
FLEETBOX_PORT="${FLEETBOX_PORT:-8000}"
FLEETBOX_DEFAULT_LOCALE="${FLEETBOX_DEFAULT_LOCALE:-de}"
FLEETBOX_ALLOW_REGISTRATION="${FLEETBOX_ALLOW_REGISTRATION:-true}"

msg() { echo -e "\e[1;32m[+]\e[0m $*"; }
die() { echo -e "\e[1;31m[x]\e[0m $*" >&2; exit 1; }

[[ -f "$INSTALL_DIR/requirements.txt" && -d "$INSTALL_DIR/app" ]] \
  || die "FleetBox source not found in $INSTALL_DIR (expected app/ and requirements.txt)."

# ---- System packages (Debian/Ubuntu) --------------------------------------
if command -v apt-get >/dev/null 2>&1; then
  msg "Installing system packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip ca-certificates >/dev/null
else
  command -v python3 >/dev/null 2>&1 || die "python3 is required but not found."
fi

# ---- Virtual environment + dependencies -----------------------------------
msg "Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ---- Configuration (.env) --------------------------------------------------
if [[ -f "$INSTALL_DIR/.env" ]]; then
  msg ".env already exists — keeping it."
else
  msg "Generating .env with a random secret key..."
  SECRET=$("$INSTALL_DIR/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")
  mkdir -p "$INSTALL_DIR/data"
  cat > "$INSTALL_DIR/.env" <<EOF
FLEETBOX_SECRET_KEY=${SECRET}
FLEETBOX_DATABASE_URL=sqlite:///${INSTALL_DIR}/data/fleetbox.db
FLEETBOX_HOST=0.0.0.0
FLEETBOX_PORT=${FLEETBOX_PORT}
FLEETBOX_DEFAULT_LOCALE=${FLEETBOX_DEFAULT_LOCALE}
FLEETBOX_ALLOW_REGISTRATION=${FLEETBOX_ALLOW_REGISTRATION}
# Set to true when serving over HTTPS behind a reverse proxy (nginx/Caddy):
FLEETBOX_SECURE_COOKIES=${FLEETBOX_SECURE_COOKIES:-false}
# Trusted reverse-proxy IP(s) for X-Forwarded-* headers (comma-separated, or *).
# Set this to your nginx host's IP for stricter security.
FLEETBOX_FORWARDED_ALLOW_IPS=${FLEETBOX_FORWARDED_ALLOW_IPS:-127.0.0.1}
EOF
fi

# ---- Database --------------------------------------------------------------
msg "Initializing the database..."
( cd "$INSTALL_DIR" && "$INSTALL_DIR/.venv/bin/python" -m app.cli init-db )

# ---- Dedicated service user ------------------------------------------------
# Run FleetBox as an unprivileged system user rather than root.
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  msg "Creating service user '$SERVICE_USER'..."
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER" 2>/dev/null \
    || useradd --system --home-dir "$INSTALL_DIR" --shell /bin/false "$SERVICE_USER"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# ---- systemd service -------------------------------------------------------
if command -v systemctl >/dev/null 2>&1; then
  msg "Installing systemd service..."
  cat > /etc/systemd/system/fleetbox.service <<EOF
[Unit]
Description=FleetBox vehicle management
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${FLEETBOX_PORT} --proxy-headers --forwarded-allow-ips=\${FLEETBOX_FORWARDED_ALLOW_IPS}
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
# The app only needs to write its data directory (SQLite DB):
ReadWritePaths=${INSTALL_DIR}/data

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now fleetbox.service
  msg "Service 'fleetbox' enabled and started (running as '$SERVICE_USER')."
else
  msg "systemd not found — start FleetBox manually:"
  echo "  cd $INSTALL_DIR && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $FLEETBOX_PORT"
fi

msg "Done. The first account you register becomes the administrator."
