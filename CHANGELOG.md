# Changelog

All notable changes to FleetBox are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Full backup as ZIP**: the Backup page now offers a one-click complete
  backup — a single ZIP archive containing every CSV export plus all uploaded
  documents & photos. Importing the archive restores data and files in one
  step: existing vehicles (matched by name) stay untouched, documents that
  already exist (same filename & size) are skipped, and attachments are
  re-linked to their service record when it can be identified unambiguously.
  Files from the archive are always written under fresh server-generated names
  inside the upload directory (zip-slip safe) and respect the upload size cap.

### Changed
- **Modernized Apple skin**: token-driven stylesheet rewrite with
  cross-document view transitions, fluid type via `clamp()`, `color-mix()`
  state colors, tinted status badges, a subtle aurora mesh background and a
  blue-to-indigo gradient accent. CSS-only; the Classic skin is untouched.

## [0.11.0] - 2026-07-06

### Added
- **Switchable design skins**: a new **Style** switch (Apple / Classic) in the
  top bar, alongside the existing theme switch. "Apple" is the refined,
  spacious default look; "Classic" restores the previous design. The choice
  persists in the session and is fully independent of the light/dark/auto theme,
  so any of the four combinations works. Each skin is a self-contained
  stylesheet (`style.css` / `classic.css`), both precached for offline use.

## [0.10.0] - 2026-07-06

### Added
- **Chain service type**: new "Kette" / "Chain" maintenance type for tracking
  chain maintenance (e.g. bicycles, motorcycles).
- **Docker step-by-step guide** (`docs/docker-step-by-step.md`): full Docker /
  Compose walkthrough covering the secret key, persistent uploads, updates,
  backup/restore, HTTPS reverse proxy, email reminders and PostgreSQL.

### Fixed
- **Docker uploads now persist**: `docker-compose.yml` sets
  `FLEETBOX_UPLOAD_DIR=/data/uploads` so uploaded documents and photos are stored
  in the `fleetbox-data` volume instead of the ephemeral container filesystem.

## [0.10.0-beta.1] - 2026-06-21

### Changed
- **Visual refresh**: a more modern, cohesive look across all pages — refined
  colour tokens and shadows, a sticky translucent top bar with pill navigation,
  card hover elevation, zebra-striped tables, pill-shaped status badges, softer
  input focus rings and tidier empty states. Pure CSS (plus one class tweak); no
  behaviour, layout or markup logic changed, and light/dark/auto themes all keep
  working.

## [0.9.0] - 2026-06-21

### Added
- **Edit service records**: existing service entries can now be edited (not just
  added or deleted), the same way refuelings already could. The vehicle's
  mileage is kept in sync when an edited record reports a higher reading.

### Changed
- **Fractional readings**: odometer and hour-meter readings (km and operating
  hours) now accept up to 2 decimal places — on vehicles, fuel logs, service
  records and service intervals. Whole numbers are still shown without trailing
  decimals.

## [0.8.0] - 2026-06-17

### Added
- **Other expenses** per vehicle: track costs that are neither fuel nor service
  — insurance, road tax, parking, tolls, the Austrian motorway vignette, fines,
  accessories and so on — each with a category, amount, date and notes. They
  count towards the vehicle's total cost and the monthly cost chart on the
  statistics page, and are included in the CSV backup (export & import).

## [0.7.0] - 2026-06-17

### Added
- **Fuel log improvements**: existing refuelings can now be **edited** (not just
  added/deleted); the log table shows **per-fill consumption** and a summary line
  (total filled, total cost, average consumption and average price); and the unit
  price is now derived from total ÷ quantity when only the receipt total is
  entered (previously only the reverse).

## [0.6.0] - 2026-06-17

### Added
- **Roadworthiness inspection date** per vehicle (§57a "Pickerl" / TÜV/HU): set
  the next inspection due date on a vehicle and FleetBox flags it as due-soon
  (within 30 days) or overdue on the dashboard and in the `send-reminders` email
  digest. The date is included in the CSV vehicle export/import.

### Fixed
- `scripts/update.sh` no longer falsely reports the systemd service as "not
  found" (and skips the restart). The existence check used `systemctl
  list-unit-files | grep -q`, which under `set -o pipefail` propagated a SIGPIPE
  failure from `systemctl` when `grep -q` closed the pipe early; it now uses
  `systemctl cat`.

## [0.5.0] - 2026-06-15

### Added
- **Tyre / seasonal tracker**: manage summer, winter and all-season tyre sets
  per vehicle (label, size, storage location, tread depth). Mount/unmount a set
  with one click — mounting records the date and the current reading and
  automatically unmounts the previous set.
- **Reminders & email notifications**: a new `fleetbox send-reminders` command
  emails each opted-in user a digest of due/overdue service intervals and
  seasonal tyre-change suggestions. Seasonal suggestions also appear on the
  dashboard. SMTP is configured via `FLEETBOX_SMTP_*`; the switch months are
  configurable (`FLEETBOX_WINTER_TIRE_MONTH` / `FLEETBOX_SUMMER_TIRE_MONTH`).
  Users can opt out under Account → Notifications. Run the command from cron or
  a systemd timer (see [configuration.md](docs/configuration.md)).

## [0.4.0] - 2026-06-15

### Added
- **Progressive Web App**: FleetBox is now installable on phones and desktops
  ("Add to Home Screen"). Ships a web app manifest, app icons and a service
  worker that provides a small offline fallback page. The service worker caches
  only static assets (cache-first) and never user data; app pages stay
  network-first, so authenticated content is always fresh. Installing requires
  HTTPS (see [reverse-proxy.md](docs/reverse-proxy.md)).
- **iOS support**: dedicated Apple touch icon, full-screen standalone mode with
  a translucent status bar, and safe-area insets so the UI clears the notch and
  home indicator on installed home-screen apps.
- **Mobile optimization**: stacked top bar with a full-width search row, larger
  touch targets, horizontally scrollable wide tables, and inputs sized to avoid
  iOS zoom-on-focus.

## [0.3.0] - 2026-06-15

### Added
- **Dark mode**: a theme switch (Auto / Light / Dark) in the top bar. "Auto"
  follows the operating system's `prefers-color-scheme`; the choice persists in
  the session. Implemented purely via CSS variables — no JavaScript, CSP-safe.
- **Vehicle title image**: mark any uploaded photo as the vehicle's title image
  (the first uploaded image is chosen automatically). It is shown in the vehicle
  list cards and the detail header, and can be switched or cleared with one click.

## [0.2.0] - 2026-06-15

### Added
- **Documentation** link in the UI footer, configurable via `FLEETBOX_DOCS_URL`
  (set empty to hide it).
- **Search** across the user's own vehicles (name, make, model, license plate,
  VIN, notes) and performed work / service records (title, workshop, notes),
  with a search box in the top bar. Ownership-scoped and LIKE-wildcard-safe.
- `scripts/update.sh` — one-command in-place update for Git-based installs:
  backs up the database, pulls the latest code, refreshes dependencies and
  restarts the service (schema auto-migration runs on restart).
- Lightweight **automatic schema migration** on startup: missing columns are
  added to existing tables via `ALTER TABLE … ADD COLUMN` (with a default derived
  from the model), so upgrades no longer require a manual `ALTER` or a database
  reset for additive changes.
- Vehicles can be tracked by **distance (km)** or **operating hours (h)** via a
  per-vehicle usage unit (for tractors, boats, generators, …). All readings,
  service intervals and statistics adapt: hour-based vehicles report consumption
  per hour and cost per hour instead of per 100 km / per km.
- Document & photo uploads per vehicle (invoices, receipts, pictures), optionally
  linked to a service record. Images preview inline; PDFs download. Restricted to
  JPEG/PNG/GIF/WebP/PDF with a configurable size cap (`FLEETBOX_UPLOAD_DIR`,
  `FLEETBOX_MAX_UPLOAD_BYTES`).
- CSV export & import for backup and migration: per-entity CSV files (vehicles,
  service records, intervals, fuel logs) under a new **Backup** page. Child rows
  reference their vehicle by name; importing into a fresh account recreates the
  data, deduping vehicles by name and skipping rows for unknown vehicles.
- Per-vehicle **statistics** page: average fuel consumption (full-to-full
  method), total/fuel/service costs, cost per km, and server-rendered SVG charts
  for monthly cost, consumption over time and mileage development. Charts are
  dependency-free and CSP-safe (no JavaScript).

## [0.1.0] - 2026-06-15

### Added
- Multi-user accounts with session-based authentication and admin user management.
- Optional per-user TOTP two-factor authentication with QR-code enrollment,
  a two-step login challenge, and a `disable-2fa` CLI recovery command.
- Vehicle management (make, model, year, VIN, license plate, mileage, fuel type).
- Service records: oil changes, brake replacements, inspections, wear parts, repairs.
- Recurring service intervals by distance (km) and/or time (months) with
  due-soon / overdue status badges.
- Fuel log with quantity, price per unit, total cost and full-tank flag.
- Dashboard with upcoming/overdue services and recent refuelings.
- German and English user interface with per-request locale resolution.
- Reverse-proxy / HTTPS support: `FLEETBOX_SECURE_COOKIES` and
  `FLEETBOX_FORWARDED_ALLOW_IPS` settings, uvicorn `--proxy-headers`, and an
  nginx walkthrough (`docs/reverse-proxy.md`).
- Local (no-GitHub) installation via `proxmox/fleetbox-local.sh` and the shared
  `scripts/install.sh` provisioning script.
- Security hardening pack: CSRF tokens on all forms, per-IP login/2FA rate
  limiting, security headers (CSP/X-Frame-Options/HSTS), TOTP secrets encrypted
  at rest, password-length policy, default-secret-key startup guard, systemd
  least-privilege sandboxing (dedicated `fleetbox` user), and CI security
  scanning (bandit, pip-audit, Dependabot).
- Proxmox VE LXC installer (`proxmox/fleetbox.sh`), Docker image and
  docker-compose deployment.
- CLI: `init-db`, `create-admin`, `serve`.
- Test suite and GitHub Actions CI.
