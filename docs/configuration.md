# Configuration

FleetBox is configured through environment variables (optionally loaded from a
`.env` file in the working directory). All variables are prefixed with
`FLEETBOX_`.

| Variable                     | Default                          | Description                                                        |
|------------------------------|----------------------------------|--------------------------------------------------------------------|
| `FLEETBOX_SECRET_KEY`        | *(insecure dev default)*         | **Required in production.** Signs session cookies.                 |
| `FLEETBOX_DATABASE_URL`      | `sqlite:///./data/fleetbox.db`   | SQLAlchemy database URL.                                            |
| `FLEETBOX_HOST`              | `0.0.0.0`                        | Bind address (used by `app.cli serve`).                            |
| `FLEETBOX_PORT`              | `8000`                           | Bind port.                                                         |
| `FLEETBOX_DEFAULT_LOCALE`    | `de`                             | Default UI language (`de` or `en`).                               |
| `FLEETBOX_ALLOW_REGISTRATION`| `true`                           | Allow visitors to self-register. Set `false` for admin-only.       |
| `FLEETBOX_SESSION_MAX_AGE`   | `1209600` (14 days)              | Session cookie lifetime in seconds.                                |
| `FLEETBOX_SECURE_COOKIES`    | `false`                          | Add the `Secure` flag to the session cookie. Set `true` when served over HTTPS (reverse proxy). |
| `FLEETBOX_FORWARDED_ALLOW_IPS`| `127.0.0.1`                     | Trusted reverse-proxy IP(s) for uvicorn's `X-Forwarded-*` handling. Comma-separated, or `*`.    |
| `FLEETBOX_MIN_PASSWORD_LENGTH`| `8`                             | Minimum password length on registration / user creation.                                        |
| `FLEETBOX_RATE_LIMIT_MAX_ATTEMPTS`| `10`                        | Failed login/2FA attempts allowed per client IP within the window.                              |
| `FLEETBOX_RATE_LIMIT_WINDOW_SECONDS`| `300`                     | Rate-limit window in seconds.                                                                   |
| `FLEETBOX_UPLOAD_DIR`        | `./data/uploads`                 | Where uploaded documents/photos are stored. Relative paths resolve against the project root.    |
| `FLEETBOX_MAX_UPLOAD_BYTES`  | `10485760` (10 MiB)              | Maximum size per uploaded file, in bytes.                                                       |
| `FLEETBOX_DOCS_URL`          | project docs on GitHub           | Target of the "Documentation" link in the UI footer. Set empty to hide it.                      |
| `FLEETBOX_BASE_URL`          | *(empty)*                        | Public URL used for links in reminder emails. Empty omits the link.                             |
| `FLEETBOX_SMTP_HOST`         | *(empty)*                        | SMTP server for reminder emails. Reminders are only sent when this is set.                       |
| `FLEETBOX_SMTP_PORT`         | `587`                            | SMTP port.                                                                                       |
| `FLEETBOX_SMTP_USER`         | *(empty)*                        | SMTP username (login). Leave empty for an unauthenticated relay.                                 |
| `FLEETBOX_SMTP_PASSWORD`     | *(empty)*                        | SMTP password.                                                                                   |
| `FLEETBOX_SMTP_FROM`         | *(falls back to user)*           | From address for reminder emails.                                                                |
| `FLEETBOX_SMTP_STARTTLS`     | `true`                           | Upgrade the connection with STARTTLS (typical for port 587).                                     |
| `FLEETBOX_SMTP_SSL`          | `false`                          | Use implicit TLS (typical for port 465); overrides STARTTLS.                                     |
| `FLEETBOX_WINTER_TIRE_MONTH` | `10`                             | Month (1-12) in which to remind users to fit winter tyres.                                       |
| `FLEETBOX_SUMMER_TIRE_MONTH` | `4`                              | Month (1-12) in which to remind users to fit summer tyres.                                       |

## File uploads

Each vehicle can hold documents and photos (invoices, receipts, pictures), which
may optionally be linked to a service record. Files are written to
`FLEETBOX_UPLOAD_DIR` under an opaque random name; only metadata is stored in the
database. Allowed types are JPEG, PNG, GIF, WebP and PDF; anything else is
rejected. Include the upload directory in your backups alongside the database.

## Backup & migration (CSV)

The **Backup** page (in the top navigation) exports each entity type as a CSV
file — vehicles, service records, service intervals and fuel logs — scoped to the
logged-in user. Child records reference their vehicle by **name** rather than a
database id, so an export can be imported into a fresh account on another
FleetBox instance.

On import, upload any of those CSVs together: vehicles are processed first, then
child rows are linked to their vehicle by name. Vehicles that already exist (by
name) are left untouched, and rows referencing an unknown vehicle are skipped.
For a complete backup, also copy the database and the upload directory
(`FLEETBOX_UPLOAD_DIR`); uploaded files themselves are not part of the CSV export.

## Reminders & notifications

FleetBox can email each user a digest of what is due:

- **Service intervals** that are due soon or overdue.
- **Roadworthiness inspection** (§57a "Pickerl" / TÜV/HU) — when a vehicle's
  `inspection_due` date is within 30 days (due soon) or in the past (overdue).
  Also shown on the dashboard.
- **Seasonal tyre changes** — when, in `FLEETBOX_WINTER_TIRE_MONTH` /
  `FLEETBOX_SUMMER_TIRE_MONTH`, a vehicle owns a tyre set for the upcoming
  season that is not the one currently mounted (see the tyre tracker on each
  vehicle page). Seasonal suggestions also appear on the dashboard.

Each user can opt out under **Account → Notifications** (`notify_email`).

Configure SMTP (see the table above), then run the command periodically — it
sends one email per user who has something due:

```bash
python -m app.cli send-reminders            # send now
python -m app.cli send-reminders --dry-run  # preview without sending or needing SMTP
```

Schedule it once a day, e.g. with **cron**:

```cron
0 8 * * *  cd /opt/fleetbox && /opt/fleetbox/.venv/bin/python -m app.cli send-reminders
```

…or a **systemd timer** (`/etc/systemd/system/fleetbox-reminders.{service,timer}`):

```ini
# fleetbox-reminders.service
[Service]
Type=oneshot
User=fleetbox
WorkingDirectory=/opt/fleetbox
EnvironmentFile=/opt/fleetbox/.env
ExecStart=/opt/fleetbox/.venv/bin/python -m app.cli send-reminders

# fleetbox-reminders.timer
[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now fleetbox-reminders.timer
```

## Running behind a reverse proxy (HTTPS)

When FleetBox sits behind nginx/Caddy terminating TLS, set
`FLEETBOX_SECURE_COOKIES=true` and `FLEETBOX_FORWARDED_ALLOW_IPS` to your proxy's
IP. The systemd service runs uvicorn with `--proxy-headers
--forwarded-allow-ips=${FLEETBOX_FORWARDED_ALLOW_IPS}` so the original `https`
scheme is honored. Full nginx walkthrough: [reverse-proxy.md](reverse-proxy.md).

## Generating a secret key

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Database backends

**SQLite (default)** — zero-config, single file. Good for households and small
fleets:

```
FLEETBOX_DATABASE_URL=sqlite:////opt/fleetbox/data/fleetbox.db
```

**PostgreSQL** — install the extra (`pip install -r requirements.txt` already
includes `psycopg`) and point the URL at your server:

```
FLEETBOX_DATABASE_URL=postgresql+psycopg://fleetbox:secret@db-host:5432/fleetbox
```

After changing the backend, run `python -m app.cli init-db` once to create the
schema.

## First administrator

- **Self-registration on:** the very first registered user automatically
  becomes an administrator.
- **Self-registration off:** create the first admin from the CLI:

  ```bash
  python -m app.cli create-admin
  ```
