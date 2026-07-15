"""Security pack 3: per-account lockout, forgot-password flow, admin-2FA policy."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import User

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    resp = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    assert match, f"no CSRF token found on {url} (status {resp.status_code})"
    return match.group(1)


def _register(client, username: str, email: str):
    token = _csrf(client, "/register")
    return client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _login(client, identifier: str, password: str):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"identifier": identifier, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


# --- Per-account lockout ------------------------------------------------------

def test_account_locks_after_repeated_failures(client, monkeypatch):
    monkeypatch.setattr(settings, "account_lockout_max_attempts", 3)
    _register(client, "victim", "victim@example.com")

    attacker = TestClient(app)  # separate session, not logged in
    for _ in range(3):
        r = _login(attacker, "victim", "wrong-password")
        assert r.status_code == 200  # re-rendered login with an error

    # Even the CORRECT password is now rejected while the account is locked.
    r = _login(attacker, "victim", PASSWORD)
    assert r.status_code == 200
    assert "gesperrt" in r.text.lower() or "locked" in r.text.lower()


def test_successful_login_clears_failure_count(client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "account_lockout_max_attempts", 3)
    _register(client, "carla", "carla@example.com")

    attacker = TestClient(app)
    for _ in range(2):  # below the threshold, not locked yet
        assert _login(attacker, "carla", "nope").status_code == 200

    r = _login(attacker, "carla", PASSWORD)
    assert r.status_code == 303  # success -> redirect to dashboard

    db_session.expire_all()
    user = db_session.query(User).filter_by(username="carla").first()
    assert user.failed_login_count == 0
    assert user.locked_until is None


# --- Forgot / reset password --------------------------------------------------

def _enable_mail(monkeypatch) -> dict:
    """Configure SMTP + base URL and capture outgoing mail; return the capture."""
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "base_url", "http://fleet.test")
    sent: dict = {}

    def fake_send(to, subject, body):
        sent.update(to=to, subject=subject, body=body)

    monkeypatch.setattr("app.routers.auth.send_email", fake_send)
    return sent


def test_forgot_and_reset_password(client, monkeypatch):
    sent = _enable_mail(monkeypatch)
    _register(client, "dora", "dora@example.com")

    anon = TestClient(app)
    csrf = _csrf(anon, "/forgot")
    r = anon.post(
        "/forgot", data={"identifier": "dora@example.com", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert sent["to"] == "dora@example.com"

    token = re.search(r"/reset\?token=(\S+)", sent["body"]).group(1)
    assert anon.get(f"/reset?token={token}").status_code == 200

    csrf = _csrf(anon, f"/reset?token={token}")
    r = anon.post(
        "/reset",
        data={"token": token, "new_password": "BrandNew123",
              "new_password_repeat": "BrandNew123", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "zurückgesetzt" in r.text.lower() or "reset" in r.text.lower()

    # New password works, old one does not.
    assert _login(TestClient(app), "dora", "BrandNew123").status_code == 303
    assert _login(TestClient(app), "dora", PASSWORD).status_code == 200

    # The token is single-use / now invalid.
    again = anon.get(f"/reset?token={token}").text
    assert "ungültig" in again.lower() or "invalid" in again.lower()


def test_forgot_unknown_user_is_generic_and_sends_nothing(client, monkeypatch):
    sent = _enable_mail(monkeypatch)

    anon = TestClient(app)
    csrf = _csrf(anon, "/forgot")
    r = anon.post(
        "/forgot", data={"identifier": "ghost@example.com", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 200
    # Same generic confirmation as for a real account (no enumeration)...
    assert "gesendet" in r.text.lower() or "sent" in r.text.lower()
    # ...and no email was actually sent.
    assert sent == {}


def test_password_reset_ends_other_sessions(client, monkeypatch):
    sent = _enable_mail(monkeypatch)
    _register(client, "erik", "erik@example.com")  # `client` is now logged in as erik
    assert client.get("/dashboard").status_code == 200

    anon = TestClient(app)
    csrf = _csrf(anon, "/forgot")
    anon.post("/forgot", data={"identifier": "erik", "csrf_token": csrf},
              follow_redirects=False)
    token = re.search(r"/reset\?token=(\S+)", sent["body"]).group(1)
    csrf = _csrf(anon, f"/reset?token={token}")
    anon.post(
        "/reset",
        data={"token": token, "new_password": "Rotated123",
              "new_password_repeat": "Rotated123", "csrf_token": csrf},
        follow_redirects=False,
    )

    # erik's original session (in `client`) is invalidated by the reset.
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("/login")


# --- 2FA required for admins --------------------------------------------------

def test_admin_2fa_policy_gates_admin_area(client, monkeypatch):
    monkeypatch.setattr(settings, "require_admin_2fa", True)
    _register(client, "boss", "boss@example.com")  # first user -> admin, no 2FA

    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("/account/security")

    # The security page explains why.
    page = client.get("/account/security").text
    assert "zwei-faktor" in page.lower() or "two-factor" in page.lower()


def test_admin_area_open_without_policy(client):
    _register(client, "boss2", "boss2@example.com")
    # Default policy is off, so the admin can reach the admin area directly.
    assert client.get("/admin/users").status_code == 200
