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
