# Changelog

All notable changes to FleetBox are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
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
