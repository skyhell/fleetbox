# Docker installation — step by step

This guide walks you through running FleetBox with Docker / Docker Compose, from
nothing installed to a running, persistent instance. The repository ships a
[`Dockerfile`](../Dockerfile) and a ready-to-use
[`docker-compose.yml`](../docker-compose.yml); Compose is the recommended way to
run it.

> **TL;DR**
>
> ```bash
> git clone https://github.com/skyhell/fleetbox.git
> cd fleetbox
> # set a real FLEETBOX_SECRET_KEY in docker-compose.yml (see Step 3)
> docker compose up -d
> ```
>
> Then open `http://<host-ip>:8000` and register — the first account becomes the
> administrator.

## Prerequisites

- A host with **Docker Engine 20.10+** and the **Compose v2** plugin
  (`docker compose`, not the old `docker-compose`). Works on Linux, macOS,
  Windows (Docker Desktop) and any NAS/VPS that runs Docker.
- Port `8000` free on the host (or pick another — see Step 3).
- Internet access on first build (to pull the Python base image and pip deps).

Check your installation:

```bash
docker --version
docker compose version
```

> No Docker yet? On Debian/Ubuntu the quickest path is the official convenience
> script: `curl -fsSL https://get.docker.com | sh`. On Windows/macOS install
> [Docker Desktop](https://www.docker.com/products/docker-desktop/).

## Step 1 — Get the code

```bash
git clone https://github.com/skyhell/fleetbox.git
cd fleetbox
```

(If you forked the project, clone your own fork instead.)

## Step 2 — Generate a secret key

FleetBox signs its session cookies with `FLEETBOX_SECRET_KEY`. **Never run with
the placeholder value in production.** Generate a random one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# or, without Python:
openssl rand -base64 48
```

Keep the output for the next step.

## Step 3 — Configure `docker-compose.yml`

Open `docker-compose.yml` and adjust the `environment:` block. The shipped file
looks like this:

```yaml
services:
  fleetbox:
    build: .
    image: fleetbox:latest
    container_name: fleetbox
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      FLEETBOX_SECRET_KEY: "change-me-please-generate-a-random-value"
      FLEETBOX_DATABASE_URL: "sqlite:////data/fleetbox.db"
      # Keep uploaded documents/photos in the persistent volume too:
      FLEETBOX_UPLOAD_DIR: "/data/uploads"
      FLEETBOX_DEFAULT_LOCALE: "de"
      FLEETBOX_ALLOW_REGISTRATION: "true"
    volumes:
      - fleetbox-data:/data

volumes:
  fleetbox-data:
```

What to change:

- **`FLEETBOX_SECRET_KEY`** — paste the value from Step 2. *(required)*
- **`FLEETBOX_UPLOAD_DIR: "/data/uploads"`** — already set for you. Leave it as
  is: without it, uploads would default to `/app/data/uploads` *inside* the
  container, which is **not** on the volume and would be lost when the container
  is recreated. Under `/data` they share the same persistent volume as the
  database.
- `FLEETBOX_DEFAULT_LOCALE` — `de` or `en`.
- `FLEETBOX_ALLOW_REGISTRATION` — leave `true` for the first run so you can
  register the admin; set it to `false` afterwards (see Step 6).
- **Port:** to serve on a different host port, change the *left* number, e.g.
  `"8080:8000"`. Leave the right side (`8000`) alone — that's the port inside the
  container.

> The database lives at `/data/fleetbox.db` (note the four slashes in the SQLite
> URL — that's an absolute path). The `/data` directory is a Docker **named
> volume** (`fleetbox-data`), so your data survives `docker compose down` and
> image rebuilds. See [configuration.md](configuration.md) for every available
> setting.

## Step 4 — Build and start

```bash
docker compose up -d --build
```

This builds the image and starts the container in the background. FleetBox
creates its database schema automatically on first startup (no `init-db` step
needed). Watch it come up:

```bash
docker compose logs -f
```

Verify the health endpoint:

```bash
curl -s http://localhost:8000/healthz
# -> {"status":"ok","version":"..."}
```

## Step 5 — First-run setup in the browser

1. Open `http://<host-ip>:8000` (or `http://localhost:8000` on the same machine).
2. **Register** — the first account automatically becomes the administrator.
3. Recommended right away:
   - Top-right → your username → **Account security** → **Enable 2FA**
     (scan the QR code with an authenticator app).
   - Create more users from the admin **Users** page.

## Step 6 — Lock down registration

Once your users exist, disable self-registration. Edit `docker-compose.yml`:

```yaml
      FLEETBOX_ALLOW_REGISTRATION: "false"
```

Then re-create the container to apply it:

```bash
docker compose up -d
```

## Operation & maintenance

```bash
# Status / logs
docker compose ps
docker compose logs -f

# Restart
docker compose restart

# Stop (keeps the volume / your data)
docker compose down

# Open a shell in the running container
docker compose exec fleetbox bash

# 2FA recovery if a user lost their authenticator
docker compose exec fleetbox python -m app.cli disable-2fa --username alice
```

### Updating to a new version

Pull the latest code and rebuild the image:

```bash
cd fleetbox
git pull
docker compose up -d --build
```

Your data is untouched: it lives in the `fleetbox-data` volume, not in the
image. The additive schema migration runs automatically on startup.

### Backup & restore

Everything that matters is in the `fleetbox-data` volume (`/data` →
`fleetbox.db` + `uploads/`). Back it up by copying it out of the container:

```bash
# Backup the whole data volume to a tarball on the host
docker run --rm -v fleetbox_fleetbox-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/fleetbox-backup.tar.gz -C /data .

# Restore into a fresh volume
docker run --rm -v fleetbox_fleetbox-data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/fleetbox-backup.tar.gz -C /data
```

> The volume's real name is `<project>_<volume>`. With the project folder named
> `fleetbox` it is `fleetbox_fleetbox-data`; confirm with `docker volume ls`.

For a quick SQLite-only backup you can also copy just the database file:

```bash
docker compose cp fleetbox:/data/fleetbox.db ./fleetbox-backup.db
```

## HTTPS / reverse proxy

The container speaks plain HTTP on port 8000. For a public deployment, put a
reverse proxy (Caddy, nginx or Traefik) in front of it for TLS, and set these in
the `environment:` block so secure cookies and forwarded headers work correctly:

```yaml
      FLEETBOX_SECURE_COOKIES: "true"
      FLEETBOX_FORWARDED_ALLOW_IPS: "*"   # or the proxy's container/host IP
```

See [reverse-proxy.md](reverse-proxy.md) and [security.md](security.md).

## Email reminders (optional)

To enable the due-service / inspection / tyre-swap email digests, add SMTP
settings to the `environment:` block and run the command on a schedule (e.g. a
host cron entry):

```yaml
      FLEETBOX_SMTP_HOST: "smtp.example.com"
      FLEETBOX_SMTP_PORT: "587"
      FLEETBOX_SMTP_USER: "fleetbox@example.com"
      FLEETBOX_SMTP_PASSWORD: "your-smtp-password"
      FLEETBOX_SMTP_FROM: "fleetbox@example.com"
      FLEETBOX_BASE_URL: "https://fleetbox.example.com"
```

```bash
# Test without sending:
docker compose exec fleetbox python -m app.cli send-reminders --dry-run
# Real run (e.g. from host crontab, daily):
docker compose exec -T fleetbox python -m app.cli send-reminders
```

## Using PostgreSQL instead of SQLite (optional)

SQLite is the default and is perfectly fine for a household/small fleet. To use
PostgreSQL, add a `db` service and point FleetBox at it. Note the image must be
built with the Postgres driver — add `requirements-postgres.txt` to the build or
install `psycopg` in the container.

```yaml
services:
  fleetbox:
    # ...as above, but:
    environment:
      FLEETBOX_DATABASE_URL: "postgresql+psycopg://fleetbox:secret@db:5432/fleetbox"
    depends_on:
      - db
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: fleetbox
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: fleetbox
    volumes:
      - fleetbox-pg:/var/lib/postgresql/data

volumes:
  fleetbox-data:
  fleetbox-pg:
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker compose: command not found` | Old/standalone Compose. Install the Compose v2 plugin, or use `docker-compose` (with a hyphen). |
| Port is already allocated | Something else uses `8000`. Change the left side of the port mapping, e.g. `"8080:8000"`. |
| Page not reachable | Check `docker compose ps` and `docker compose logs`; make sure you opened the **host** port you mapped. |
| Uploads disappear after rebuild | `FLEETBOX_UPLOAD_DIR` is not set to `/data/uploads` — see Step 3. |
| `Invalid secret key` / random logouts | `FLEETBOX_SECRET_KEY` changed or is still the placeholder. Set a fixed random value. |
| Cookie not set behind HTTPS proxy | Set `FLEETBOX_SECURE_COOKIES=true` and `FLEETBOX_FORWARDED_ALLOW_IPS` — see HTTPS section. |
| Want to start over | `docker compose down -v` deletes the volume **and all data**. Use with care. |
