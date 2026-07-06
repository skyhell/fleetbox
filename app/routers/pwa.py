"""Progressive Web App endpoints: web app manifest and service worker.

These make FleetBox installable ("Add to Home Screen") and give it a small,
conservative offline experience. They are intentionally public (no login or
CSRF needed) and serve no user data.

The service worker is rendered here rather than served as a static file so its
cache name can be tied to the application version: a new release automatically
invalidates the old precache. It is also served from the site root (``/sw.js``)
so its scope covers the whole app.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from app import __version__

router = APIRouter()

# Assets safe to cache aggressively (cache-first). Same-origin, versioned by the
# cache name below, never user-specific.
_PRECACHE = [
    "/static/css/style.css",
    "/static/css/classic.css",
    "/static/js/app.js",
    "/static/offline.html",
    "/static/icons/icon.svg",
    "/static/icons/icon-192.png",
]


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> JSONResponse:
    data = {
        "name": "FleetBox",
        "short_name": "FleetBox",
        "description": "Self-hosted vehicle & fleet management",
        "start_url": "/dashboard",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0f141a",
        "theme_color": "#2563eb",
        "icons": [
            {
                "src": "/static/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
            },
        ],
    }
    return JSONResponse(data, media_type="application/manifest+json")


# Cache name is bumped automatically with every release.
_SW_JS = """\
const CACHE = "fleetbox-%(version)s";
const PRECACHE = %(precache)s;
const OFFLINE = "/static/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // App navigations: network-first, fall back to a cached offline page.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }

  // Static assets: cache-first, then network (and cache the result).
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req).then((hit) =>
        hit || fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
          return res;
        })
      )
    );
  }
});
"""


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    body = _SW_JS % {"version": __version__, "precache": json.dumps(_PRECACHE)}
    return Response(
        content=body,
        media_type="application/javascript",
        headers={
            # Allow the worker to control the whole site even though the file
            # lives at the root, and never let the worker script itself be
            # served stale.
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )
