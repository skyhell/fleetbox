# Security

This page documents FleetBox's built-in protections and how to harden a
deployment.

## Built-in protections (overview)

| Control | What it does |
|---|---|
| **bcrypt password hashing** | No plaintext passwords are stored. |
| **Signed session cookies** | `starlette.SessionMiddleware`, `SameSite=Lax`, optional `Secure`. |
| **CSRF tokens** | Every state-changing form carries a per-session token, validated in constant time. |
| **Login rate limiting** | Per-IP throttling of failed login and 2FA attempts (brute-force defence). |
| **TOTP 2FA** | Optional per user; the seed is encrypted at rest. |
| **Security headers** | CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and HSTS over HTTPS. |
| **Ownership checks** | A user can only access their own vehicles/records; admin actions are gated separately. |
| **Password policy** | Minimum length enforced on registration / user creation. |
| **Secret-key guard** | The app refuses to start in HTTPS mode with the default `SECRET_KEY`. |
| **Least privilege** | systemd service runs as a dedicated non-root user with sandboxing. |

## Authentication

FleetBox uses session cookies signed with `FLEETBOX_SECRET_KEY`
(`starlette.SessionMiddleware`). Passwords are hashed with **bcrypt**. Always
set a strong, random `FLEETBOX_SECRET_KEY` in production — see
[configuration.md](configuration.md). If `FLEETBOX_SECURE_COOKIES=true` while the
key is still the built-in default, the app **refuses to start**.

## CSRF protection

All unsafe requests (POST and friends) must include a `csrf_token` that matches
the per-session token; otherwise they are rejected with `403`. The token is
injected into every form automatically. Confirm dialogs use a small static JS
file (`/static/js/app.js`) so a strict Content-Security-Policy can be enforced
without inline scripts.

## Rate limiting

Failed login and 2FA attempts are throttled per client IP
(`FLEETBOX_RATE_LIMIT_MAX_ATTEMPTS` per `FLEETBOX_RATE_LIMIT_WINDOW_SECONDS`).
This is an in-memory limiter suited to a single-process deployment; for
multi-process/multi-host setups, add per-IP limits at your reverse proxy or back
the limiter with Redis.

## Security headers

A middleware sets `Content-Security-Policy` (`default-src 'self'`),
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and
`Referrer-Policy: no-referrer` on every response. When `FLEETBOX_SECURE_COOKIES`
is enabled (HTTPS), `Strict-Transport-Security` is added too.

## Two-factor authentication (2FA)

Each user can enable **time-based one-time password (TOTP, RFC 6238)** 2FA from
**Account security** (click your username in the top bar → *Account security*).

### Enabling 2FA

1. Go to **Account security** and click **Enable 2FA**.
2. Scan the displayed QR code with an authenticator app such as Aegis,
   Google Authenticator, Microsoft Authenticator or 1Password — or type the
   shown secret in manually.
3. Enter the current 6-digit code to confirm. 2FA is now active.

### Logging in with 2FA

After entering a correct username/password, users with 2FA enabled are sent to a
second step (`/login/2fa`) and must enter the current 6-digit code. Codes are
accepted within a ±1 time-step window (≈30 s) to tolerate clock drift.

The TOTP seed is **encrypted at rest** (Fernet, key derived from
`FLEETBOX_SECRET_KEY`). Rotating the secret key therefore invalidates existing
2FA enrollments — affected users must re-enroll (or an admin runs `disable-2fa`).

### Disabling 2FA

From **Account security**, enter a current code and click **Disable 2FA**.

### Account recovery (lost authenticator)

If a user loses access to their authenticator app, an administrator with shell
access to the host can disable 2FA from the CLI:

```bash
python -m app.cli disable-2fa --username alice
# or by email:
python -m app.cli disable-2fa --email alice@example.com
```

On a Proxmox install this runs inside the container:

```bash
pct exec <CTID> -- /opt/fleetbox/.venv/bin/python -m app.cli disable-2fa --username alice
```

## Service isolation

The provided systemd unit (from `scripts/install.sh` and the Proxmox installers)
runs FleetBox as a dedicated unprivileged **`fleetbox`** user with sandboxing:
`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
`ProtectKernel*`, `RestrictSUIDSGID` and a single writable path
(`/opt/fleetbox/data`). If you run FleetBox yourself, mirror this — never run it
as root.

## Supply-chain / CI

The CI pipeline runs **bandit** (static analysis) and **pip-audit** (dependency
CVE scan), and **Dependabot** (`.github/dependabot.yml`) opens weekly update PRs
for pip and GitHub Actions. For reproducible production builds, pin exact
versions with `pip freeze > requirements.lock`.

## Hardening recommendations

- Put FleetBox behind a TLS-terminating reverse proxy (Caddy, nginx, Traefik) and
  set `FLEETBOX_SECURE_COOKIES=true`. See [reverse-proxy.md](reverse-proxy.md).
- Set a strong random `FLEETBOX_SECRET_KEY` (the app refuses to start in HTTPS
  mode with the default).
- Set `FLEETBOX_ALLOW_REGISTRATION=false` once your users exist, and create
  further accounts from the admin **Users** page.
- Encourage every user to enable 2FA.
- Add per-IP rate limiting at the reverse proxy as a second layer.
- Keep the host and Python dependencies up to date (Dependabot helps here).
- Back up `/opt/fleetbox/data/fleetbox.db` regularly.
