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
│   ├── charts.py          # Dependency-free SVG chart rendering
│   ├── cli.py             # init-db / create-admin / disable-2fa / serve
│   ├── routers/           # auth, account, dashboard, vehicles, service, fuel,
│   │                      #   stats, attachments, backup, admin
│   ├── templates/         # Jinja2 HTML templates
│   ├── locales/           # de.json, en.json translation catalogs
│   └── static/            # CSS / assets
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

## Running tests

```bash
pytest
```

## Linting & formatting

```bash
ruff check app tests
ruff format app tests
```

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
