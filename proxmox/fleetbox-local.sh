#!/usr/bin/env bash
#
# FleetBox — Proxmox VE LXC installer WITHOUT GitHub
# --------------------------------------------------
# Run this ON THE PROXMOX HOST, from inside a local copy of the FleetBox repo.
# It packages the local source, creates a Debian 12 LXC container, copies the
# code into it (via `pct push`) and installs FleetBox — no Git or external
# repository required.
#
#   # copy the project to the host first, e.g. with scp, then:
#   cd /root/fleetbox
#   bash proxmox/fleetbox-local.sh
#
# Configurable via environment variables (all optional):
#   CTID, HOSTNAME, DISK_GB, CORES, RAM_MB, BRIDGE, STORAGE, TEMPLATE, FLEETBOX_PORT
#
set -euo pipefail

# Locate the repository root (the parent directory of this script's folder).
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CTID="${CTID:-}"
HOSTNAME="${HOSTNAME:-fleetbox}"
DISK_GB="${DISK_GB:-4}"
CORES="${CORES:-1}"
RAM_MB="${RAM_MB:-512}"
BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
TEMPLATE="${TEMPLATE:-debian-12-standard}"
FLEETBOX_PORT="${FLEETBOX_PORT:-8000}"

msg()  { echo -e "\e[1;32m[+]\e[0m $*"; }
warn() { echo -e "\e[1;33m[!]\e[0m $*"; }
die()  { echo -e "\e[1;31m[x]\e[0m $*" >&2; exit 1; }

command -v pct >/dev/null 2>&1 || die "This script must run on a Proxmox VE host (pct not found)."
[[ -f "$SRC_DIR/requirements.txt" && -d "$SRC_DIR/app" ]] \
  || die "Run this from inside the FleetBox repo (app/ and requirements.txt not found in $SRC_DIR)."

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

# ---- Package the local source ---------------------------------------------
msg "Packaging local source from $SRC_DIR ..."
TARBALL="$(mktemp /tmp/fleetbox-src-XXXXXX.tar.gz)"
tar czf "$TARBALL" -C "$SRC_DIR" \
  --exclude='./.venv' \
  --exclude='./.git' \
  --exclude='./data' \
  --exclude='./__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='./.pytest_cache' \
  --exclude='./.ruff_cache' \
  --exclude='./.mypy_cache' \
  --exclude='*.pyc' \
  .

# ---- Copy into the container and extract ----------------------------------
msg "Copying source into the container..."
pct exec "$CTID" -- mkdir -p /opt/fleetbox
pct push "$CTID" "$TARBALL" /tmp/fleetbox-src.tar.gz
pct exec "$CTID" -- tar xzf /tmp/fleetbox-src.tar.gz -C /opt/fleetbox
pct exec "$CTID" -- rm -f /tmp/fleetbox-src.tar.gz
rm -f "$TARBALL"

# ---- Provision inside the container ---------------------------------------
msg "Running the in-container installer..."
pct exec "$CTID" -- env FLEETBOX_PORT="$FLEETBOX_PORT" bash /opt/fleetbox/scripts/install.sh

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
msg "Done!"
echo
echo "  FleetBox is running in container $CTID (installed from local source)."
echo "  Open:  http://${IP}:${FLEETBOX_PORT}"
echo
echo "  The first account you register becomes the administrator."
echo "  Logs:  pct exec $CTID -- journalctl -u fleetbox -f"
