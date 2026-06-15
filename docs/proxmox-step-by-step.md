# Proxmox installation — step by step

This guide walks you through installing FleetBox on Proxmox VE from scratch. The
installer (`proxmox/fleetbox.sh`) creates an unprivileged Debian 12 LXC
container and runs FleetBox as a systemd service.

> **Important:** the installer fetches the code with `git clone`, so FleetBox
> must be available in a Git repository first. Push it to GitHub (Step 1) or
> point `REPO_URL` at your own repository.

## Prerequisites

- Proxmox VE 7 or 8 with shell/root access to the **host** (not a guest)
- A template storage (default `local`) and a disk storage (default `local-lvm`)
- Internet access from the host (template + package download)
- FleetBox available in a reachable Git repository (e.g. GitHub)

## Step 1 — Push the code to GitHub

On your workstation, in the project folder:

```bash
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/skyhell/fleetbox.git
git push -u origin main
```

The repository URLs already point to `skyhell`. If you forked this project,
replace `skyhell` with your own GitHub user in:

- `README.md`
- `proxmox/fleetbox.sh` (the `REPO_URL` variable)

> No GitHub? Skip this step and pass your own `REPO_URL=...` in Step 3, or use
> the manual/no-Git approach at the bottom of this page.

## Step 2 — Open a shell on the Proxmox host

Use SSH, or the Proxmox web UI: **Datacenter → your node → Shell**. You are now
`root` on the host. Verify you are really on the host:

```bash
pct list        # only exists on the Proxmox host
```

## Step 3 — Run the installer

Defaults:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/skyhell/fleetbox/main/proxmox/fleetbox.sh)"
```

With custom values (more RAM/disk, fixed container id, your own repo):

```bash
CTID=151 HOSTNAME=garage DISK_GB=6 RAM_MB=1024 CORES=2 \
REPO_URL=https://github.com/skyhell/fleetbox.git \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/skyhell/fleetbox/main/proxmox/fleetbox.sh)"
```

All variables (optional):

| Variable        | Default       | Meaning                     |
|-----------------|---------------|-----------------------------|
| `CTID`          | next free id  | Container ID                |
| `HOSTNAME`      | `fleetbox`    | Hostname                    |
| `DISK_GB`       | `4`           | Disk size in GB             |
| `CORES`         | `1`           | CPU cores                   |
| `RAM_MB`        | `512`         | Memory in MB                |
| `BRIDGE`        | `vmbr0`       | Network bridge              |
| `STORAGE`       | `local-lvm`   | Root disk storage           |
| `REPO_URL`      | your repo     | Git source                  |
| `FLEETBOX_PORT` | `8000`        | Service port                |

## What the installer does

1. Picks a free container ID (`pvesh get /cluster/nextid`).
2. Downloads the Debian 12 LXC template if needed.
3. Creates an **unprivileged** LXC (DHCP, `nesting=1`, `onboot=1`).
4. Installs `git`, `python3`, `venv` inside the container.
5. Clones FleetBox into `/opt/fleetbox` and creates a virtualenv with deps.
6. Writes `.env` with a **randomly generated `FLEETBOX_SECRET_KEY`** and a
   SQLite database under `/opt/fleetbox/data/`.
7. Initializes the database (`app.cli init-db`).
8. Installs and starts the `fleetbox` systemd service.
9. Prints the container IP and URL.

## Step 4 — First-run setup in the browser

1. Open the printed address, e.g. `http://192.168.x.y:8000`.
2. **Register** — the first account automatically becomes the administrator.
3. Recommended right away:
   - Top-right → your username → **Account security** → **Enable 2FA**
     (scan the QR code with an authenticator app).
   - Create more users from the admin **Users** page.

Disable self-registration once your users exist:

```bash
pct exec <CTID> -- sed -i 's/FLEETBOX_ALLOW_REGISTRATION=true/FLEETBOX_ALLOW_REGISTRATION=false/' /opt/fleetbox/.env
pct exec <CTID> -- systemctl restart fleetbox
```

## Operation & maintenance

```bash
# Status / logs
pct exec <CTID> -- systemctl status fleetbox
pct exec <CTID> -- journalctl -u fleetbox -f

# Restart
pct exec <CTID> -- systemctl restart fleetbox

# Update to a new version
pct exec <CTID> -- bash -c "cd /opt/fleetbox && git pull && .venv/bin/pip install -r requirements.txt && systemctl restart fleetbox"

# 2FA recovery if a user lost their authenticator
pct exec <CTID> -- /opt/fleetbox/.venv/bin/python -m app.cli disable-2fa --username alice
```

**Backup:** it is enough to back up the SQLite file
`/opt/fleetbox/data/fleetbox.db` inside the container.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `pct: command not found` | You are not on the host. Switch to the Proxmox host. |
| `Template … not found` | Run `pveam update`; optionally set `TEMPLATE_STORAGE=local`. |
| `git clone` fails / 404 | Wrong `REPO_URL` or private repo. Fix the URL or make it public. |
| Page not reachable | Check IP with `pct exec <CTID> -- hostname -I` and read the logs. |
| Want HTTPS | Put Caddy/nginx/Traefik in front — see [security.md](security.md). |

## Installing without GitHub

If you do not want to publish FleetBox to a Git repository, use the local
installer instead. It packages the source on the host and pushes it into the
container — no Git, no internet repository required.

### Option A — automated (`proxmox/fleetbox-local.sh`)

1. Copy the FleetBox project folder onto the Proxmox host, e.g. with `scp`:

   ```bash
   # from your workstation
   scp -r ./fleetbox root@PROXMOX-HOST:/root/fleetbox
   ```

2. On the host, run the local installer from inside that folder:

   ```bash
   cd /root/fleetbox
   bash proxmox/fleetbox-local.sh
   ```

   The same `CTID`, `HOSTNAME`, `DISK_GB`, … environment variables as the
   GitHub installer apply. The script creates the LXC, copies the code to
   `/opt/fleetbox`, and runs `scripts/install.sh` inside the container.

### Option B — fully manual

Create a container yourself, copy the source into `/opt/fleetbox`
(`scp` / `pct push`), then run the shared provisioning script inside it:

```bash
pct exec <CTID> -- bash /opt/fleetbox/scripts/install.sh
```

`scripts/install.sh` also works on any plain Debian/Ubuntu host (no Proxmox):
copy the project to `/opt/fleetbox` and run `sudo bash scripts/install.sh`.
