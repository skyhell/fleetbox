"""End-to-end tests for the main user flows and security controls."""

from __future__ import annotations

import re

from app.config import settings

PASSWORD = "Secret123"  # >= min_password_length


def _csrf(client, url: str) -> str:
    """Fetch a page and extract its CSRF token (also primes the session cookie)."""
    html = client.get(url).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"no CSRF token found on {url}"
    return match.group(1)


def _register(client, username: str, email: str, password: str = PASSWORD):
    token = _csrf(client, "/register")
    return client.post(
        "/register",
        data={"username": username, "email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_security_headers_present(client):
    resp = client.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in resp.headers


def test_root_redirects_to_login_when_anonymous(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_register_first_user_becomes_admin_and_can_use_app(client):
    resp = _register(client, "alice", "alice@example.com")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"

    assert client.get("/dashboard").status_code == 200
    # First user is admin.
    assert client.get("/admin/users").status_code == 200


def test_register_rejects_short_password(client):
    token = _csrf(client, "/register")
    resp = client.post(
        "/register",
        data={
            "username": "shorty",
            "email": "s@example.com",
            "password": "abc",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200  # re-rendered with an error, not logged in


def test_post_without_csrf_token_is_forbidden(client):
    resp = client.post(
        "/register",
        data={"username": "mallory", "email": "m@example.com", "password": PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_vehicle_crud_and_ownership(client):
    _register(client, "bob", "bob@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={
            "name": "Golf",
            "make": "VW",
            "mileage": "120000",
            "fuel_type": "diesel",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    detail_url = resp.headers["location"]

    page = client.get(detail_url)
    assert page.status_code == 200
    assert "Golf" in page.text

    token = _csrf(client, detail_url)
    resp = client.post(
        f"{detail_url}/records",
        data={
            "service_type": "oil_change",
            "title": "Ölwechsel 5W30",
            "performed_on": "2026-01-10",
            "mileage": "121000",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Ölwechsel 5W30" in client.get(detail_url).text


def test_vehicle_with_operating_hours(client):
    _register(client, "tractor", "tractor@example.com")

    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={
            "name": "Fendt",
            "usage_unit": "h",
            "mileage": "3500",
            "fuel_type": "diesel",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    detail = resp.headers["location"]

    # The reading is labelled in hours, not km.
    page = client.get(detail).text
    assert "3500 h" in page
    assert "3500 km" not in page
    # The list view reflects the unit too.
    assert "3500 h" in client.get("/vehicles").text


def test_two_factor_enrollment_and_login(client):
    import pyotp

    from app import database
    from app.crypto import encrypt
    from app.models import User

    _register(client, "dave", "dave@example.com")

    # Enable 2FA directly on the user, storing the secret encrypted at rest
    # (as the enable endpoint does).
    secret = pyotp.random_base32()
    db = database.SessionLocal()
    try:
        user = db.query(User).filter(User.username == "dave").first()
        user.totp_secret = encrypt(secret)
        user.totp_enabled = True
        db.commit()
    finally:
        db.close()

    client.get("/logout")

    # Password alone now redirects to the 2FA challenge.
    token = _csrf(client, "/login")
    resp = client.post(
        "/login",
        data={"identifier": "dave", "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login/2fa"

    # Wrong code rejected.
    token = _csrf(client, "/login/2fa")
    bad = client.post(
        "/login/2fa", data={"code": "000000", "csrf_token": token}, follow_redirects=False
    )
    assert bad.status_code == 200

    # Correct current code completes the login.
    token = _csrf(client, "/login/2fa")
    good = client.post(
        "/login/2fa",
        data={"code": pyotp.TOTP(secret).now(), "csrf_token": token},
        follow_redirects=False,
    )
    assert good.status_code == 303
    assert good.headers["location"] == "/dashboard"
    assert client.get("/dashboard").status_code == 200


def test_login_logout(client):
    _register(client, "carol", "carol@example.com")
    client.get("/logout")

    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)

    token = _csrf(client, "/login")
    bad = client.post(
        "/login",
        data={"identifier": "carol", "password": "wrong", "csrf_token": token},
        follow_redirects=False,
    )
    assert bad.status_code == 200

    token = _csrf(client, "/login")
    ok = client.post(
        "/login",
        data={"identifier": "carol", "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert ok.status_code == 303


def test_login_rate_limited_after_repeated_failures(client):
    _register(client, "rate", "rate@example.com")
    client.get("/logout")

    # Exhaust the allowed attempts with wrong passwords.
    for _ in range(settings.rate_limit_max_attempts):
        token = _csrf(client, "/login")
        client.post(
            "/login",
            data={"identifier": "rate", "password": "wrong", "csrf_token": token},
            follow_redirects=False,
        )

    # Even the *correct* password is now blocked (no redirect to dashboard).
    token = _csrf(client, "/login")
    blocked = client.post(
        "/login",
        data={"identifier": "rate", "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert blocked.status_code == 200
