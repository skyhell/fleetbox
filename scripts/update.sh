#!/usr/bin/env bash
#
# FleetBox update script
# ----------------------
# Updates an existing FleetBox install in place: backs up the SQLite database,
# pulls the latest code, refreshes dependencies and restarts the service. The
# additive schema auto-migration runs automatically on the next startup.
#
# Run as root INSIDE the target machine (the Proxmox LXC, VM or bare-metal host):
#
#   sudo bash scripts/update.sh
#   # or, for an install created by the Proxmox installer:
#   curl -fsSL https://raw.githubusercontent.com/skyhell/fleetbox/main/scripts/update.sh | sudo bash
#
# Configurable via environment variables (all optional):
#   INSTALL_DIR (default /opt/fleetbox), SERVICE_USER (fleetbox),
#   SERVICE_NAME (fleetbox), REPO_BRANCH (main)
#
# Only versioned files are touched — your .env and data/ directory are left
# untouched. This handles additive changes only; it does not roll back.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/fleetbox}"
SERVICE_USER="${SERVICE_USER:-fleetbox}"
SERVICE_NAME="${SERVICE_NAME:-fleetbox}"
REPO_BRANCH="${REPO_BRANCH:-main}"

msg()  { echo -e "\e[1;32m[+]\e[0m $*"; }
warn() { echo -e "\e[1;33m[!]\e[0m $*"; }
die()  { echo -e "\e[1;31m[x]\e[0m $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Please run as root (sudo)."
[[ -d "$INSTALL_DIR/app" ]] || die "FleetBox not found in $INSTALL_DIR (set INSTALL_DIR)."
[[ -d "$INSTALL_DIR/.git" ]] || die \
  "$INSTALL_DIR is not a Git checkout. This looks like a local-source install; \
re-copy the source and re-run scripts/install.sh instead."

# ---- 1. Back up the database ----------------------------------------------
DB_FILE="$INSTALL_DIR/data/fleetbox.db"
if [[ -f "$DB_FILE" ]]; then
  BACKUP="$DB_FILE.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$DB_FILE" "$BACKUP"
  msg "Database backed up to $BACKUP"
else
  warn "No SQLite database at $DB_FILE — skipping backup (external/Postgres DB?)."
fi

# ---- 2. Pull the latest code ----------------------------------------------
# Avoid Git's "dubious ownership" guard when running as root over a tree owned
# by the service user.
git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

OLD_REV=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
msg "Fetching latest '$REPO_BRANCH' (current: $OLD_REV)..."
git -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_BRANCH"
git -C "$INSTALL_DIR" reset --hard "origin/$REPO_BRANCH"
NEW_REV=$(git -C "$INSTALL_DIR" rev-parse --short HEAD)

if [[ "$OLD_REV" == "$NEW_REV" ]]; then
  msg "Already up to date ($NEW_REV). Restarting anyway to apply config/migrations."
else
  msg "Updated $OLD_REV -> $NEW_REV"
fi

# ---- 3. Refresh dependencies ----------------------------------------------
msg "Updating Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade -r "$INSTALL_DIR/requirements.txt"

# ---- 4. Restore ownership (git/pip ran as root) ---------------------------
if id "$SERVICE_USER" >/dev/null 2>&1; then
  chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
fi

# ---- 5. Restart (schema auto-migration runs on startup) -------------------
# Note: `systemctl cat` is a reliable existence check that returns non-zero when
# the unit is unknown. We deliberately avoid `systemctl list-unit-files | grep -q`
# here: under `set -o pipefail`, `grep -q` exits on the first match and closes
# the pipe, so `systemctl` dies with SIGPIPE (141) and pipefail propagates that
# failure even though the unit *does* exist — falsely reporting "not found".
if command -v systemctl >/dev/null 2>&1 && systemctl cat "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  msg "Restarting ${SERVICE_NAME}.service..."
  systemctl restart "$SERVICE_NAME"
  sleep 2
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    msg "Update complete — ${SERVICE_NAME} is running ($NEW_REV)."
  else
    systemctl status "$SERVICE_NAME" --no-pager || true
    die "Service failed to start. Check: journalctl -u ${SERVICE_NAME} -n 50"
  fi
else
  warn "systemd service '${SERVICE_NAME}' not found — restart FleetBox manually."
fi
