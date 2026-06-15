# Installation

FleetBox can be installed in three ways. All of them result in a web app
listening on port `8000` by default.

## 1. Proxmox VE (recommended for self-hosting)

Run the installer **on your Proxmox host** (not inside a container). It creates
an unprivileged Debian 12 LXC, installs FleetBox and registers a systemd
service:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/skyhell/fleetbox/main/proxmox/fleetbox.sh)"
```

You can customize the container via environment variables:

```bash
CTID=151 HOSTNAME=garage DISK_GB=6 RAM_MB=1024 CORES=2 \
  bash -c "$(curl -fsSL .../proxmox/fleetbox.sh)"
```

| Variable        | Default            | Meaning                          |
|-----------------|--------------------|----------------------------------|
| `CTID`          | next free id       | LXC container ID                 |
| `HOSTNAME`      | `fleetbox`         | Container hostname               |
| `DISK_GB`       | `4`                | Root disk size in GB             |
| `CORES`         | `1`                | CPU cores                        |
| `RAM_MB`        | `512`              | Memory in MB                     |
| `BRIDGE`        | `vmbr0`            | Network bridge                   |
| `STORAGE`       | `local-lvm`        | Storage for the root disk        |
| `REPO_URL`      | project repo       | Git URL to clone FleetBox from   |
| `FLEETBOX_PORT` | `8000`             | Port the service listens on      |

After it finishes, open `http://<container-ip>:8000`. **The first account you
register becomes the administrator.**

Service management inside the container:

```bash
pct exec <CTID> -- systemctl status fleetbox
pct exec <CTID> -- journalctl -u fleetbox -f
```

### Without GitHub (local source)

To install on Proxmox **without** a Git repository, copy the project to the host
and run the local installer, which packages the source and pushes it into the
container:

```bash
scp -r ./fleetbox root@PROXMOX-HOST:/root/fleetbox
# on the host:
cd /root/fleetbox
bash proxmox/fleetbox-local.sh
```

The shared provisioning script `scripts/install.sh` (invoked automatically) also
works standalone on any Debian/Ubuntu host. See
[proxmox-step-by-step.md](proxmox-step-by-step.md) for details.

## 2. Docker / Docker Compose

```bash
git clone https://github.com/skyhell/fleetbox.git
cd fleetbox
# Edit docker-compose.yml and set a real FLEETBOX_SECRET_KEY
docker compose up -d
```

Data is persisted in the `fleetbox-data` named volume.

## 3. Bare metal / virtualenv

```bash
git clone https://github.com/skyhell/fleetbox.git
cd fleetbox
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set FLEETBOX_SECRET_KEY
python -m app.cli init-db
python -m app.cli create-admin --username admin --email admin@example.com --password secret
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

See [configuration.md](configuration.md) for all settings.
