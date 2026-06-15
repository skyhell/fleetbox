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
│   ├── models.py          # SQLAlchemy ORM models
│   ├── security.py        # Password hashing, auth dependencies
│   ├── totp.py            # TOTP 2FA helpers (pyotp + QR code)
│   ├── crypto.py          # Fernet encryption for secrets at rest
│   ├── csrf.py            # CSRF token generation + validation
│   ├── ratelimit.py       # In-memory per-IP rate limiter
│   ├── i18n.py            # JSON translation lookup + locale resolution
│   ├── templating.py      # Jinja2 setup + render() helper
│   ├── cli.py             # init-db / create-admin / disable-2fa / serve
│   ├── routers/           # auth, account, dashboard, vehicles, service, fuel, admin
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
- **Ownership** is enforced in every vehicle/service/fuel route: a user may only
  touch vehicles where `owner_id == user.id`. Admins manage *users*, not other
  users' vehicles.
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

This skeleton uses `Base.metadata.create_all()` (via `init-db`) rather than
migrations. For production schema changes, introduce
[Alembic](https://alembic.sqlalchemy.org/) — add it to `requirements.txt`,
run `alembic init alembic`, and replace the `init_db()` call accordingly.
