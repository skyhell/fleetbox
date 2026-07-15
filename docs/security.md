# Security

This page documents FleetBox's built-in protections and how to harden a
deployment.

## Built-in protections (overview)

| Control | What it does |
|---|---|
| **bcrypt password hashing** | No plaintext passwords are stored. |
| **Signed session cookies** | `starlette.SessionMiddleware`, `SameSite=Lax`, optional `Secure`; a fresh session + new CSRF token are issued on login. |
| **CSRF tokens** | Every state-changing form carries a per-session token, validated in constant time. |
| **Rate limiting** | Per-IP throttling of failed login, 2FA and registration attempts (brute-force / mass-signup defence). |
| **Account lockout** | Per-account lock after repeated failed logins, independent of IP; optional forced 2FA for admins. |
| **TOTP 2FA** | Optional per user; the seed is encrypted at rest, codes are single-use (replay-protected), with one-time recovery codes. |
| **Session invalidation** | Changing a password ends all other sessions; users can also "sign out everywhere else". |
| **Audit log** | Security-relevant events are recorded and visible to administrators. |
| **Upload validation** | Uploaded files are checked by content (magic bytes) and served sandboxed. |
| **Security headers** | CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP, and HSTS over HTTPS. |
| **Ownership checks** | A user can only access their own vehicles/records; admin actions are gated separately. |
| **Password policy** | Minimum length enforced on registration / user creation; new passwords require confirmation. |
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

Failed login, 2FA and registration attempts are throttled per client IP
(`FLEETBOX_RATE_LIMIT_MAX_ATTEMPTS` per `FLEETBOX_RATE_LIMIT_WINDOW_SECONDS`).
This is an in-memory limiter suited to a single-process deployment; for
multi-process/multi-host setups, add per-IP limits at your reverse proxy or back
the limiter with Redis.

## Account lockout

In addition to the per-IP limiter, each account has a **per-account lockout**:
after `FLEETBOX_ACCOUNT_LOCKOUT_MAX_ATTEMPTS` consecutive failed logins (password
*or* 2FA) the account is locked for `FLEETBOX_ACCOUNT_LOCKOUT_MINUTES` minutes.
While locked, even the correct password is rejected, so an attacker spread across
many IPs is still slowed per target account. The counter and lock are stored on
the user row (persisting across restarts) and cleared on the next successful
login. Lockouts are recorded in the audit log (`account.locked`, `login.blocked`).

## Password reset (forgot password)

The login page offers a **"Forgot password?"** link. A user enters their email or
username; if a matching active account exists, FleetBox emails a one-time reset
link (a random token whose SHA-256 hash and expiry are stored on the user row,
valid for `FLEETBOX_RESET_TOKEN_MINUTES`). The confirmation page is **identical
whether or not the account exists**, so the form does not reveal which addresses
are registered. Completing a reset sets the new password, consumes the token,
clears any lockout and **invalidates every other session** of that account.

This feature needs SMTP **and** `FLEETBOX_BASE_URL` configured (see
[configuration.md](configuration.md)); without them the request is accepted but
no email can be sent (a warning is logged).

## Security headers

A middleware sets these on every response:

- **`Content-Security-Policy`**: `default-src 'self'; img-src 'self' data:;
  object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'`
  — no inline scripts/styles, so all JS lives in `/static/js/app.js` and charts
  are server-rendered SVG.
- **`X-Frame-Options: DENY`** and **`X-Content-Type-Options: nosniff`**.
- **`Referrer-Policy: no-referrer`**.
- **`Permissions-Policy`**: camera, microphone, geolocation, payment and USB are
  all denied (FleetBox uses none of them).
- **`Cross-Origin-Opener-Policy: same-origin`** and
  **`Cross-Origin-Resource-Policy: same-origin`**.
- **`Strict-Transport-Security`** is added when `FLEETBOX_SECURE_COOKIES` is
  enabled (HTTPS).

Uploaded files are additionally served with `Content-Security-Policy: sandbox`,
so even a crafted file cannot run scripts against the app when opened directly.

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
second step (`/login/2fa`) and must enter the current 6-digit code — or a
recovery code (see below). Codes are accepted within a ±1 time-step window
(≈30 s) to tolerate clock drift, and each accepted code is **single-use**: a
sniffed code cannot be replayed within its window.

### Recovery codes

Enabling 2FA issues **eight one-time recovery codes**, shown exactly once and
stored only as SHA-256 hashes. At the 2FA login step a recovery code can be
entered in place of an authenticator code; it is consumed on use. Keep them
somewhere safe — they are the self-service way back in if the authenticator app
is lost.

The TOTP seed is **encrypted at rest** (Fernet, key derived from
`FLEETBOX_SECRET_KEY`). Rotating the secret key therefore invalidates existing
2FA enrollments — affected users must re-enroll (or an admin runs `disable-2fa`).

### Disabling 2FA

From **Account security**, enter a current code and click **Disable 2FA**.

### Account recovery (lost authenticator)

The first line of recovery is one of the user's own **recovery codes** (above),
entered at the 2FA login step. If those are also lost, an administrator with
shell access to the host can disable 2FA from the CLI:

```bash
python -m app.cli disable-2fa --username alice
# or by email:
python -m app.cli disable-2fa --email alice@example.com
```

On a Proxmox install this runs inside the container:

```bash
pct exec <CTID> -- /opt/fleetbox/.venv/bin/python -m app.cli disable-2fa --username alice
```

### Requiring 2FA for administrators

Set `FLEETBOX_REQUIRE_ADMIN_2FA=true` to make two-factor authentication
mandatory for admin accounts. An administrator without 2FA is then redirected to
**Account security** (which stays reachable so they can enable it) and cannot use
the admin area until they do. Non-admin users are unaffected.

## Passwords & sessions

- **Change your own password** from **Account security** (requires the current
  password; the new one must be entered twice).
- **Fresh session on login**: completing a login clears any pre-login session
  state and rotates the CSRF token (session-fixation hygiene); theme/skin
  preferences are kept.
- **Session invalidation**: sessions are stateless signed cookies, so they
  cannot be deleted server-side individually. Instead each user carries a
  `session_generation` counter that sessions remember. Changing a password (or
  an admin resetting it) **bumps the counter, invalidating every other session**
  of that account; the session that made the change is re-stamped and stays
  logged in.
- **Sign out everywhere else**: the same mechanism is exposed as a button on
  **Account security** — one click ends all of the account's other sessions.
- **Logout is POST-only** with a CSRF token, so link prefetching or an old
  bookmark cannot end a session.

## Audit log

Security-relevant events are recorded to an append-only audit trail and shown to
administrators under **Users → Audit log** (`/admin/audit`, newest first): logins
and failed attempts, logouts, registrations, password and 2FA changes, admin
user management, and "sign out everywhere". Each entry keeps a snapshot of the
acting/attempted username, the client IP and a UTC timestamp, so it stays
meaningful even after the user is renamed or deleted.

## File uploads

Uploaded documents and photos are validated by **content, not just the declared
type**: the file's leading bytes must match a supported format (JPEG, PNG, GIF,
WebP or PDF), so a mislabelled or empty file is rejected with `415`. The same
check runs on files restored from a ZIP backup. Files are stored under
`FLEETBOX_UPLOAD_DIR` with opaque, server-generated names (never the client's
path — zip-slip safe) and are capped at `FLEETBOX_MAX_UPLOAD_BYTES`. Downloads
are served with `Content-Security-Policy: sandbox` (see *Security headers*).

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
