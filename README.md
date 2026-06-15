# FleetBox

> A self-hosted, multi-user vehicle and fleet management application — inspired by
> [Homebox](https://github.com/sysadminsmedia/homebox), but focused purely on vehicles.

FleetBox helps you keep track of your cars, motorcycles and other vehicles:
service intervals, the last oil change, brake replacements, wearing parts and
refueling logs. It speaks **German and English** and is built to be installed on
a **Proxmox** host with a single script.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- 🚗 **Multi-vehicle management** — make, model, year, VIN, license plate, mileage or operating hours
- 🔧 **Service records** — oil changes, brake replacements, inspections, generic repairs
- ⏱️ **Service intervals** — by usage (km or operating hours) and/or time (months) with due/overdue warnings
- 🧩 **Wear parts** — tyres, brake pads, filters, belts, batteries, …
- ⛽ **Fuel log** — liters, price per liter, total cost, consumption tracking
- 🛞 **Tyre tracker** — summer/winter/all-season sets, storage location, tread depth, mount/unmount with reading
- 🔔 **Reminders** — email digests for due services and seasonal tyre changes (opt-in per user)
- 🔎 **Search** — find vehicles and performed work (service records) across your fleet
- 📊 **Statistics** — fuel consumption, costs per month and mileage trends as charts
- 📎 **Documents & photos** — attach invoices, receipts and pictures; set one photo as the vehicle's title image
- 💾 **CSV backup & migration** — export and re-import all your data
- 👥 **Multi-user** — each user manages their own vehicles; an admin manages users
- 🔐 **Two-factor authentication** — optional TOTP 2FA per user (Aegis, Google Authenticator, 1Password, …)
- 🛡️ **Hardened by default** — CSRF tokens, login rate limiting, security headers, encrypted 2FA seeds, non-root systemd sandbox ([details](docs/security.md))
- 🌍 **Internationalization** — full UI in German (`de`) and English (`en`)
- 🌗 **Dark mode** — auto (follows your OS), light or dark, switchable in the top bar
- 📱 **Installable PWA** — add FleetBox to your phone's home screen, mobile-optimized UI, offline fallback
- 📦 **Easy deployment** — Proxmox LXC install script, Docker, or bare `pip`

## Quick start (development)

```bash
git clone https://github.com/skyhell/fleetbox.git
cd fleetbox
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # adjust the SECRET_KEY at minimum
python -m app.cli init-db     # create tables + first admin user
uvicorn app.main:app --reload
```

Then open <http://localhost:8000>.

## Install on Proxmox

Run the following on your **Proxmox VE host** (creates a Debian LXC container and
installs FleetBox as a systemd service):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/skyhell/fleetbox/main/proxmox/fleetbox.sh)"
```

This uses [`proxmox/fleetbox.sh`](proxmox/fleetbox.sh), which clones the code from
GitHub. The full walkthrough is in
[`docs/proxmox-step-by-step.md`](docs/proxmox-step-by-step.md)
([HTML version](docs/proxmox-step-by-step.html)).

### Without GitHub (local source)

To install from a local copy — no Git repository required — copy the project to
the host and run the local installer:

```bash
scp -r ./fleetbox root@PROXMOX-HOST:/root/fleetbox
# on the host:
cd /root/fleetbox && bash proxmox/fleetbox-local.sh
```

[`proxmox/fleetbox-local.sh`](proxmox/fleetbox-local.sh) packages the source and
pushes it into the container, then runs the shared provisioning script
[`scripts/install.sh`](scripts/install.sh). That script also works standalone on
any Debian/Ubuntu host (`sudo bash scripts/install.sh`).

See [`docs/installation.md`](docs/installation.md) for all installation methods.

## Documentation

All documentation lives in [`docs/`](docs/) and is written in **English**:

- [Installation](docs/installation.md)
- [Proxmox install — step by step](docs/proxmox-step-by-step.md) ([HTML version](docs/proxmox-step-by-step.html))
- [Configuration](docs/configuration.md)
- [Reverse proxy & HTTPS (nginx)](docs/reverse-proxy.md)
- [Development guide](docs/development.md)
- [Security & 2FA](docs/security.md)
- [Internationalization](docs/i18n.md)
- [Data model](docs/data-model.md)

## License

[MIT](LICENSE)
