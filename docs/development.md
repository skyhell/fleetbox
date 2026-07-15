# Development guide

## Prerequisites

- Python 3.11+
- Git

## Setup

```bash
git clone https://github.com/skyhell/fleetbox.git
cd fleetbox
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m app.cli init-db
uvicorn app.main:app --reload
```

Open <http://localhost:8000> and register the first (admin) account.

## Project layout

```
fleetbox/
├── app/
│   ├── main.py            # FastAPI app, middleware, router wiring
│   ├── config.py          # Settings (pydantic-settings)
│   ├── database.py        # Engine, session, Base, init_db()
│   ├── migrations.py      # Additive auto-migration (ALTER TABLE ADD COLUMN)
│   ├── models.py          # SQLAlchemy ORM models
│   ├── security.py        # Password hashing, auth dependencies
│   ├── totp.py            # TOTP 2FA helpers (pyotp + QR code)
│   ├── crypto.py          # Fernet encryption for secrets at rest
│   ├── csrf.py            # CSRF token generation + validation
│   ├── ratelimit.py       # In-memory per-IP rate limiter
│   ├── i18n.py            # JSON translation lookup + locale resolution
│   ├── templating.py      # Jinja2 setup + render() helper
│   ├── stats.py           # Per-vehicle statistics computation
│   ├── reports.py         # Fleet-wide yearly cost report aggregation
│   ├── charts.py          # Dependency-free SVG chart rendering
│   ├── audit.py           # Audit-log helper (records security events)
│   ├── reminders.py       # Due-service, inspection & seasonal-tyre reminder collection
│   ├── mailer.py          # Minimal stdlib SMTP sender
│   ├── cli.py             # init-db / create-admin / disable-2fa / send-reminders / serve
│   ├── routers/           # auth, account, dashboard, vehicles, service, fuel,
│   │                      #   expenses, reports, stats, tires, attachments,
│   │                      #   search, backup, admin, pwa
│   ├── templates/         # Jinja2 HTML templates
│   ├── locales/           # de.json, en.json translation catalogs
│   └── static/            # CSS / JS / app icons / offline.html
├── proxmox/fleetbox.sh    # Proxmox LXC installer
├── docs/                  # English documentation
└── tests/                 # pytest test suite
```

## Architecture

- **FastAPI** serves server-rendered HTML (Jinja2) — no separate frontend build.
- **Sessions** are signed cookies (`starlette.SessionMiddleware`); the user id
  is stored in the session and resolved to a `User` on each request.
- **Ownership** is enforced in every vehicle-scoped route (service, fuel, stats,
  attachments, backup): a user may only touch vehicles where
  `owner_id == user.id`. Admins manage *users*, not other users' vehicles.
- **Charts** are rendered server-side as SVG (`charts.py`) with no JavaScript or
  external library, so they work under the strict Content-Security-Policy.
- **i18n** is intentionally dependency-free: flat JSON catalogs and a `t()`
  helper injected into every template. See [i18n.md](i18n.md).
- **PWA**: `app/routers/pwa.py` serves the web app manifest
  (`/manifest.webmanifest`) and the service worker (`/sw.js`, served from the
  root so its scope covers the whole app). The service worker's cache name is
  tied to the app version, so each release invalidates the old precache. It
  caches only `/static/` assets (cache-first) and falls back to
  `static/offline.html` for navigations while offline — app pages themselves are
  always fetched network-first, so authenticated content is never served stale.

## Regenerating the app icons

The PWA icons in `app/static/icons/` are checked into the repository, so the
running app never needs an image library. To regenerate them (e.g. after a
design change), install Pillow and run the generator:

```bash
pip install pillow
python scripts/make_icons.py
```

## Running tests

```bash
pytest
```

### How the suite is wired

`tests/conftest.py` gives every test an isolated **in-memory SQLite database**
(`sqlite://` on a `StaticPool`, so all connections share one database) and points
the app's session factory at it, so routes and assertions see the same data. Two
fixtures cover the two levels tests are written at:

- **`client`** — boots the real FastAPI app through Starlette's `TestClient`.
  Exercises the full HTTP path: session cookies, CSRF, ownership checks,
  rendered templates. Use it for anything a browser would hit.
- **`db_session`** — a plain SQLAlchemy session, no web layer. Use it for
  computation (`stats.py`, `reports.py`, `reminders.py`, `models.py`).

An autouse fixture resets the rate limiters in `app/routers/auth.py` around every
test. They are module-level (process-wide) state, so without the reset a test
that exhausts the login limit would lock out unrelated tests that log in later.

### What the suite covers

| Area | Files | What is asserted |
| --- | --- | --- |
| Security | `test_app`, `test_security_pack`, `test_security_pack2`, `test_security_pack3`, `test_admin_edit` | Security headers, CSRF rejection, registration rules, 2FA enrollment + TOTP replay, recovery codes, per-IP rate limits and per-account lockout, forgot/reset password, upload magic-byte sniffing, session invalidation after a password change, audit log, admin-2FA policy, admin user editing incl. the self-demotion guard |
| Domain logic | `test_stats`, `test_reminders`, `test_reports_pack`, `test_models` | Full-to-full and partial-fill consumption, electric and hour-based vehicles, yearly cost aggregation, service-interval status, §57a inspection thresholds, seasonal tyre logic, reminder email rendering |
| CRUD & flows | `test_vehicle_photo`, `test_service`, `test_fuel`, `test_fuel_types`, `test_expenses`, `test_tires`, `test_attachments`, `test_quick_add`, `test_search`, `test_readings`, `test_usability` | Create/edit/delete per entity, ownership enforcement on every vehicle-scoped route, upload validation, decimal readings, repeat-entry prefill |
| Backup | `test_backup` | CSV and ZIP export/import round-trips, no duplicate vehicles on re-import, invalid archives rejected |
| Presentation & infra | `test_pwa`, `test_theme`, `test_skin`, `test_i18n`, `test_migrations` | Manifest and service worker, theme/skin switching, translation lookup and locale resolution, additive auto-migration |

Ownership is the cross-cutting concern: every vehicle-scoped feature has a test
that registers a second user and asserts they get a **404, not a 403** — the app
does not confirm that a foreign id exists. Search is the exception, since it is a
query rather than an id lookup: `test_search_respects_ownership` asserts the
foreign vehicle is simply absent from the results.

### Browser end-to-end smoke test

The unit suite never runs JavaScript, so a small Playwright script exercises the
JS-driven behaviour (table pagination, the print button, the report pages)
against a live server. It seeds a throwaway database, starts uvicorn and drives
Chromium, then tears everything down:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium   # one-time browser download
python scripts/verify_e2e.py
```

It exits non-zero if any check fails. CI runs the same script in the `e2e` job.

## Linting & formatting

```bash
ruff check app tests
ruff format app tests
```

## What CI runs

`.github/workflows/ci.yml` runs on every push to `main`, on every pull request,
and on a weekly schedule (Mondays 06:00 UTC) so new advisories surface even when
nothing is pushed. Three jobs:

| Job | Steps |
| --- | --- |
| `test` | `ruff check app tests`, then `pytest` — on Python 3.11 **and** 3.12 |
| `e2e` | Installs Chromium, runs `python scripts/verify_e2e.py` |
| `security` | `bandit -r app -c pyproject.toml`, then `pip-audit` |

`pip-audit` is `continue-on-error` on pushes and PRs, so a freshly published
advisory does not block unrelated work; the weekly scheduled run fails hard
instead. Bandit's config lives in `pyproject.toml` (`[tool.bandit]`), which skips
B104 — binding to `0.0.0.0` is intentional behind a reverse proxy.

## Adding a database column

The schema is created with `Base.metadata.create_all()` (via `init-db`). On top
of that, `app/migrations.py` runs a **lightweight additive auto-migration** on
every startup: it compares the ORM metadata to the live database and issues
`ALTER TABLE … ADD COLUMN` for any missing column, deriving a `DEFAULT` from the
column's scalar default so existing rows stay valid.

So for most changes you just:

1. Add the column to the model in `app/models.py` (give `NOT NULL` columns a
   scalar `default=` so existing rows can be back-filled).
2. Restart the app — the new column is added automatically.

This only ever *adds* columns and tables. **Renames, drops and type changes are
out of scope** — for those, introduce a real migration tool such as
[Alembic](https://alembic.sqlalchemy.org/) (`alembic init alembic`, then replace
the `init_db()` call).
