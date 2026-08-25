#!/usr/bin/env python3
"""End-to-end smoke test: drive a real browser against a live FleetBox.

Covers the JavaScript-driven behaviour the unit tests (which never run JS)
cannot: table pagination ("show more"), the print button and print media, and
that the report pages render. It seeds a throwaway SQLite database, starts
uvicorn in a subprocess, drives it with Playwright/Chromium, then tears
everything down. Exits non-zero if any check fails.

Run it after installing the dev dependencies and a browser:

    pip install -r requirements-dev.txt
    python -m playwright install chromium
    python scripts/verify_e2e.py

CI runs the same script in the `e2e` job.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRET = "e2e-secret-key"

_checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    _checks.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _seed(db_path: str) -> int:
    """Create the schema and a user + vehicle + 25 service records; return its id."""
    os.environ["FLEETBOX_SECRET_KEY"] = SECRET
    os.environ["FLEETBOX_DATABASE_URL"] = f"sqlite:///{db_path}"
    sys.path.insert(0, str(REPO))

    from app.database import SessionLocal, init_db
    from app.models import (
        Expense,
        ExpenseCategory,
        FuelLog,
        ServiceInterval,
        ServiceRecord,
        ServiceType,
        User,
        Vehicle,
    )
    from app.security import hash_password

    init_db()
    db = SessionLocal()
    try:
        user = User(
            email="e2e@example.com",
            username="e2e",
            hashed_password=hash_password("Secret123"),
        )
        db.add(user)
        db.flush()
        vehicle = Vehicle(
            owner_id=user.id, name="Golf", make="VW", model="Golf",
            year=2019, license_plate="W-1234A", mileage=95000,
        )
        db.add(vehicle)
        db.flush()
        # 25 rows -> the table pages (PAGE = 20) and gets a "show more" button.
        for i in range(25):
            db.add(ServiceRecord(
                vehicle_id=vehicle.id, service_type=ServiceType.oil_change,
                title=f"Service #{i + 1}", performed_on=date(2024, 1, 1),
                mileage=1000 * (i + 1), cost=50 + i,
            ))
        # Fuel + expenses across two years so the cost report has content.
        for yr in (2024, 2025):
            db.add(FuelLog(vehicle_id=vehicle.id, filled_on=date(yr, 1, 1),
                           mileage=1000, quantity=40, total_cost=70, full_tank=True))
            db.add(FuelLog(vehicle_id=vehicle.id, filled_on=date(yr, 6, 1),
                           mileage=11000, quantity=40, total_cost=72, full_tank=True))
            db.add(Expense(vehicle_id=vehicle.id, category=ExpenseCategory.insurance,
                           title="Insurance", amount=600, spent_on=date(yr, 3, 1)))
        # Next oil change was due at 60.000 km — overdue at 95.000, so the
        # navigation badge has exactly one item to count.
        db.add(ServiceInterval(
            vehicle_id=vehicle.id, name="Oil change",
            service_type=ServiceType.oil_change,
            interval_km=15000, last_service_mileage=45000,
        ))
        db.commit()
        return int(vehicle.id)
    finally:
        db.close()


def _wait_until_up(base: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/healthz", timeout=1)
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise RuntimeError(f"server did not come up at {base}")


def _service_rows_visible(page) -> int:
    """Number of non-hidden rows in the 25-row service-records table."""
    return page.evaluate(
        "() => { const t = [...document.querySelectorAll('table[data-enhance]')]"
        ".find(t => t.tBodies[0].rows.length === 25);"
        " return t ? [...t.tBodies[0].rows].filter(r => !r.hidden).length : -1; }"
    )


def _run_browser(base: str, vehicle_id: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(f"{base}/login")
            page.fill('input[name="identifier"]', "e2e")
            page.fill('input[name="password"]', "Secret123")
            page.click('form[action="/login"] button[type="submit"]')
            page.wait_for_url(f"{base}/dashboard")

            # --- C2: pagination on the vehicle page (25 service records) ---
            page.goto(f"{base}/vehicles/{vehicle_id}")
            page.wait_for_timeout(400)
            check("pagination shows first 20 rows", _service_rows_visible(page) == 20)
            more = page.query_selector(".show-more")
            check("'show more' button present", more is not None)
            if more:
                page.eval_on_selector(".show-more", "el => el.click()")
                page.wait_for_timeout(200)
                check("all 25 rows after 'show more'", _service_rows_visible(page) == 25)
                disp = page.eval_on_selector(".show-more", "el => getComputedStyle(el).display")
                check("'show more' hides once fully revealed", disp == "none")

            # Filter searches across all rows, including collapsed pages.
            page.locator(".table-filter").first.fill("Service #24")
            page.wait_for_timeout(200)
            check("filter finds a row from a collapsed page", _service_rows_visible(page) == 1)

            # --- B1: cost report ---
            page.goto(f"{base}/reports")
            page.wait_for_timeout(300)
            html = page.content()
            check("cost report renders", "Cost report" in html or "Kostenbericht" in html)

            # --- B3: vehicle record + print stylesheet ---
            page.goto(f"{base}/vehicles/{vehicle_id}/report")
            page.wait_for_timeout(300)
            check("print button present", page.query_selector(".js-print") is not None)
            page.emulate_media(media="print")
            page.wait_for_timeout(150)
            topbar = page.eval_on_selector(".topbar", "el => getComputedStyle(el).display")
            check("app chrome hidden in print media", topbar == "none")
            page.emulate_media(media="screen")

            # --- U2: attention badge counts the overdue interval ---
            page.goto(f"{base}/dashboard")
            page.wait_for_timeout(300)
            badge = page.query_selector(".mainnav .navbadge")
            check("attention badge visible", badge is not None)
            if badge:
                check("attention badge counts the overdue interval",
                      badge.inner_text().strip() == "1")

            # --- U1: a toast confirms an action and fades on its own ---
            page.goto(f"{base}/vehicles/{vehicle_id}")
            page.wait_for_timeout(300)
            page.eval_on_selector("details.adder", "el => el.open = true")
            page.fill('form[action$="/intervals"] input[name="name"]', "Brake fluid")
            page.click('form[action$="/intervals"] button[type="submit"]')
            page.wait_for_timeout(600)
            check("toast shown after an action", page.query_selector(".toast") is not None)
            page.wait_for_timeout(6000)  # VISIBLE_MS (5s) + the fade-out
            check("toast disappears on its own", page.query_selector(".toast") is None)
            page.reload()
            page.wait_for_timeout(400)
            check("toast is one-shot", page.query_selector(".toast") is None)

            # --- U3: empty state instead of a bare dash ---
            page.goto(f"{base}/search?q=zzzzzzzz")
            page.wait_for_timeout(300)
            check("search empty state rendered",
                  page.query_selector(".empty-inline") is not None)

            # --- S4: passkeys, driven by Chromium's virtual authenticator ---
            cdp = page.context.new_cdp_session(page)
            cdp.send("WebAuthn.enable", {})
            cdp.send("WebAuthn.addVirtualAuthenticator", {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,       # discoverable -> usernameless login
                    "hasUserVerification": True,
                    "isUserVerified": True,       # "the human is present and verified"
                    "automaticPresenceSimulation": True,
                }
            })

            page.goto(f"{base}/account/security")
            page.wait_for_timeout(400)
            check(
                "passkey enrollment offered on a secure context",
                page.eval_on_selector("[data-passkey-add]", "el => !el.hidden"),
            )
            page.fill("[data-passkey-name]", "E2E key")
            page.click("[data-passkey-register]")
            page.wait_for_timeout(2000)  # ceremony + reload
            check("passkey registered", "E2E key" in page.content())

            page.click('form[action="/logout"] button[type="submit"]')
            page.wait_for_url(f"{base}/login")
            page.wait_for_timeout(400)
            check(
                "passkey login offered",
                page.eval_on_selector("[data-passkey-login-box]", "el => !el.hidden"),
            )
            page.click("[data-passkey-login]")
            page.wait_for_url(f"{base}/dashboard", timeout=15000)
            check("passwordless login succeeded", page.url.rstrip("/").endswith("/dashboard"))

            # --- A1: sign out everywhere else ---
            page.goto(f"{base}/account/security")
            page.wait_for_timeout(200)
            check(
                "'sign out everywhere' form present",
                page.query_selector('form[action="/account/logout-others"]') is not None,
            )
        finally:
            browser.close()


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="fleetbox-e2e-")
    db_path = os.path.join(tmp, "e2e.db")
    port = _free_port()
    # "localhost" rather than the bare IP: browsers treat both as secure
    # contexts, but a WebAuthn relying-party id must be a domain, and an IP
    # address is not one — the passkey checks below would fail on 127.0.0.1.
    base = f"http://localhost:{port}"

    vehicle_id = _seed(db_path)

    env = dict(os.environ)
    env["FLEETBOX_SECRET_KEY"] = SECRET
    env["FLEETBOX_DATABASE_URL"] = f"sqlite:///{db_path}"
    env["PYTHONPATH"] = str(REPO)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(REPO), env=env,
    )
    try:
        _wait_until_up(base)
        _run_browser(base, vehicle_id)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [name for name, ok in _checks if not ok]
    print()
    if failed:
        print(f"E2E FAILED: {len(failed)}/{len(_checks)} checks failed")
        return 1
    print(f"E2E OK: {len(_checks)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
