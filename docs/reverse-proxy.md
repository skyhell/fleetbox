# Reverse proxy & HTTPS (nginx)

FleetBox itself serves plain HTTP (uvicorn on port `8000`). To reach it over
**HTTPS**, terminate TLS at a reverse proxy in front of it. This page covers
**nginx** running on your Proxmox host (or a separate LXC).

## 1. Configure FleetBox for proxy operation

Two things make FleetBox behave correctly behind an HTTPS proxy:

1. **`Secure` cookie flag** — set `FLEETBOX_SECURE_COOKIES=true` so the session
   cookie is only sent over HTTPS (browser ↔ nginx is HTTPS).
2. **Trust proxy headers** — the systemd service starts uvicorn with
   `--proxy-headers --forwarded-allow-ips=${FLEETBOX_FORWARDED_ALLOW_IPS}`, so the
   original `https` scheme and client IP from nginx's `X-Forwarded-*` headers are
   honored. By default only `127.0.0.1` is trusted; set this to your **nginx
   host's IP** so FleetBox only accepts forwarded headers from your proxy.

Enable the secure cookie and pin the trusted proxy IP in the container
(replace `192.168.1.10` with your nginx host's IP):

```bash
pct exec <CTID> -- sed -i 's/FLEETBOX_SECURE_COOKIES=false/FLEETBOX_SECURE_COOKIES=true/' /opt/fleetbox/.env
pct exec <CTID> -- sed -i 's/FLEETBOX_FORWARDED_ALLOW_IPS=127.0.0.1/FLEETBOX_FORWARDED_ALLOW_IPS=192.168.1.10/' /opt/fleetbox/.env
pct exec <CTID> -- systemctl restart fleetbox
```

> If nginx runs *inside the same container*, leave `FLEETBOX_FORWARDED_ALLOW_IPS`
> at `127.0.0.1`. Use `*` only as a last resort (trusts forwarded headers from
> any source).

> Only set `FLEETBOX_SECURE_COOKIES=true` once HTTPS actually works — with the
> `Secure` flag the cookie is *not* sent over plain HTTP, so you could not log in
> via `http://`.

Find the FleetBox container's IP (you'll point nginx at it):

```bash
pct exec <CTID> -- hostname -I
```

## 2. nginx server block

Create `/etc/nginx/sites-available/fleetbox.conf` (adjust `server_name` and the
upstream IP/port — use `127.0.0.1:8000` if nginx runs *inside the same
container*, otherwise the container's LAN IP):

```nginx
upstream fleetbox {
    server 192.168.1.50:8000;   # <-- FleetBox container IP:port
}

# Redirect HTTP -> HTTPS
server {
    listen 80;
    server_name fleetbox.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name fleetbox.example.com;

    ssl_certificate     /etc/letsencrypt/live/fleetbox.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fleetbox.example.com/privkey.pem;

    # Sensible TLS defaults
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # QR-code SVGs and form posts are small; this is plenty.
    client_max_body_size 4m;

    location / {
        proxy_pass         http://fleetbox;
        proxy_http_version 1.1;

        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;   # <-- tells FleetBox it's HTTPS
        proxy_set_header   X-Forwarded-Host  $host;

        proxy_read_timeout 60s;
    }
}
```

Enable it and reload:

```bash
ln -s /etc/nginx/sites-available/fleetbox.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 3. TLS certificate

### Public domain — Let's Encrypt (certbot)

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d fleetbox.example.com
```

certbot fills in the `ssl_certificate*` paths and sets up auto-renewal.

### LAN only / no public domain

Let's Encrypt needs a publicly resolvable domain. For a purely internal setup,
either use a certificate from your own internal CA, or terminate TLS at an
existing internal proxy (e.g. Nginx Proxy Manager, OPNsense). Point the same
`proxy_pass` upstream at the FleetBox container.

## 4. Verify

```bash
curl -I https://fleetbox.example.com/healthz
```

You should get `HTTP/2 200`. Then log in over `https://` — the browser should
keep the session (the `Secure` cookie now works because the connection is HTTPS).

## Installing as an app (PWA)

FleetBox is a Progressive Web App: it can be installed to a phone's home screen
or a desktop as a standalone app. This **requires HTTPS** — browsers only
register a service worker on a secure origin (the sole exception is
`http://localhost` during development). Once served over HTTPS as above:

- **Android / Chrome / Edge**: an install prompt appears, or use the browser
  menu → *Install app*.
- **iOS / Safari**: there is no automatic prompt — open the Share sheet and tap
  *Add to Home Screen*. The app then runs full-screen with its own icon.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Login loops / "not logged in" after submitting | `FLEETBOX_SECURE_COOKIES=true` but you opened the site over plain `http://`. Use `https://`. |
| `502 Bad Gateway` | Wrong upstream IP/port, or FleetBox not running. Check `systemctl status fleetbox` and the container IP. |
| Redirects go to `http://` | Missing `proxy_set_header X-Forwarded-Proto $scheme;` (FleetBox uses relative redirects, but this keeps everything consistent). |
| Cert errors on a LAN host | No public domain → Let's Encrypt won't issue. Use an internal CA. |
| No "Install app" option / offline page never shows | The service worker only registers over HTTPS (or `http://localhost`). Serve FleetBox over HTTPS. |
