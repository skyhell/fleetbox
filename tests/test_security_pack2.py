"""Second security pack: register rate limit, upload magic bytes,
session invalidation on password change, audit log."""

from __future__ import annotations

import re

PASSWORD = "Secret123"

# A minimal valid 1x1 PNG.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f1e0000000049454e44ae42"
    "6082"
)


def _csrf(client, url: str) -> str:
    resp = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    assert match, f"no CSRF token found on {url} (status {resp.status_code})"
    return match.group(1)


def _register(client, username: str, email: str, password: str = PASSWORD):
    token = _csrf(client, "/register")
    return client.post(
        "/register",
        data={"username": username, "email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _login(client, identifier: str, password: str = PASSWORD):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"identifier": identifier, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _logout(client):
    return client.post(
        "/logout",
        data={"csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )


def _second_client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def _create_vehicle(client) -> str:
    token = _csrf(client, "/vehicles/new")
    resp = client.post(
        "/vehicles/new",
        data={"name": "Golf", "mileage": "100", "fuel_type": "diesel", "csrf_token": token},
        follow_redirects=False,
    )
    return resp.headers["location"]


# --- Register rate limit ------------------------------------------------------


def test_register_is_rate_limited(client):
    from app.config import settings

    # Exhaust the per-IP budget with (cheap) invalid attempts.
    for i in range(settings.rate_limit_max_attempts):
        _register(client, f"u{i}", f"u{i}@example.com", password="x")

    resp = _register(client, "late", "late@example.com")
    assert resp.status_code == 200  # re-rendered with an error, no account
    assert "alert-error" in resp.text
    # The account was really not created.
    assert _login(client, "late").status_code == 200


# --- Upload magic bytes -------------------------------------------------------


def test_upload_rejects_mislabelled_content(client, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    _register(client, "alice", "alice@example.com")
    vehicle_url = _create_vehicle(client)

    token = _csrf(client, vehicle_url)
    resp = client.post(
        f"{vehicle_url}/attachments",
        data={"csrf_token": token, "title": "Evil"},
        files={"file": ("x.png", b"<html><script>alert(1)</script></html>", "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 415
    # Nothing was stored on disk.
    upload_dir = tmp_path / "uploads"
    assert not upload_dir.exists() or not any(upload_dir.iterdir())


def test_upload_accepts_matching_content_and_sandboxes_download(
    client, tmp_path, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    _register(client, "bob", "bob@example.com")
    vehicle_url = _create_vehicle(client)

    token = _csrf(client, vehicle_url)
    resp = client.post(
        f"{vehicle_url}/attachments",
        data={"csrf_token": token, "title": "Photo"},
        files={"file": ("ok.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get(vehicle_url).text
    attachment_url = re.search(rf"{vehicle_url}/attachments/\d+", page).group(0)
    download = client.get(attachment_url)
    assert download.status_code == 200
    # User-uploaded content is served in an origin-less sandbox.
    assert download.headers["content-security-policy"] == "sandbox"


def test_upload_rejects_empty_file(client, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    _register(client, "carl", "carl@example.com")
    vehicle_url = _create_vehicle(client)

    token = _csrf(client, vehicle_url)
    resp = client.post(
        f"{vehicle_url}/attachments",
        data={"csrf_token": token, "title": "Empty"},
        files={"file": ("e.png", b"", "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 415


# --- Session invalidation on password change ----------------------------------


def test_password_change_ends_other_sessions(client):
    _register(client, "dora", "dora@example.com")

    with _second_client() as other:
        assert _login(other, "dora").status_code == 303
        assert other.get("/dashboard").status_code == 200

        # Change the password in the first session.
        token = _csrf(client, "/account/security")
        resp = client.post(
            "/account/password",
            data={
                "current_password": PASSWORD,
                "new_password": "Brandneu123",
                "new_password_repeat": "Brandneu123",
                "csrf_token": token,
            },
        )
        assert "alert-success" in resp.text

        # The changing session survives; the other session is dead.
        assert client.get("/dashboard").status_code == 200
        assert other.get("/dashboard", follow_redirects=False).status_code == 303


def test_admin_password_reset_ends_target_sessions(client):
    _register(client, "admin", "admin@example.com")
    token = _csrf(client, "/admin/users")
    client.post(
        "/admin/users",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": PASSWORD,
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    with _second_client() as worker:
        assert _login(worker, "worker").status_code == 303
        assert worker.get("/dashboard").status_code == 200

        token = _csrf(client, "/admin/users/2/edit")
        resp = client.post(
            "/admin/users/2/edit",
            data={
                "username": "worker",
                "email": "worker@example.com",
                "password": "Zurueckgesetzt1",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # The worker's old session is gone; the new password logs in again.
        assert worker.get("/dashboard", follow_redirects=False).status_code == 303
        assert _login(worker, "worker", "Zurueckgesetzt1").status_code == 303


def test_relogin_after_password_change_works(client):
    _register(client, "emil", "emil@example.com")
    token = _csrf(client, "/account/security")
    client.post(
        "/account/password",
        data={
            "current_password": PASSWORD,
            "new_password": "NochNeuer123",
            "new_password_repeat": "NochNeuer123",
            "csrf_token": token,
        },
    )
    _logout(client)
    assert _login(client, "emil", "NochNeuer123").status_code == 303
    assert client.get("/dashboard").status_code == 200


# --- Audit log ------------------------------------------------------------


def test_audit_log_records_security_events(client):
    _register(client, "admin", "admin@example.com")

    # Provoke a failed login from a second session.
    with _second_client() as other:
        _login(other, "admin", "definitiv-falsch")

    _logout(client)
    _login(client, "admin")

    page = client.get("/admin/audit")
    assert page.status_code == 200
    html = page.text
    assert "audit" in html.lower()
    for needle in ("Registrierung", "Anmeldung", "Fehlgeschlagene Anmeldung", "Abmeldung"):
        assert needle in html, f"missing event: {needle}"
    assert "admin" in html


def test_audit_log_records_password_change(client):
    _register(client, "admin", "admin@example.com")
    token = _csrf(client, "/account/security")
    client.post(
        "/account/password",
        data={
            "current_password": PASSWORD,
            "new_password": "Gewechselt123",
            "new_password_repeat": "Gewechselt123",
            "csrf_token": token,
        },
    )
    html = client.get("/admin/audit").text
    assert "Passwort ge" in html  # "Passwort geändert" (umlaut-safe)


def test_audit_log_is_admin_only(client):
    _register(client, "admin", "admin@example.com")
    token = _csrf(client, "/admin/users")
    client.post(
        "/admin/users",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": PASSWORD,
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    _logout(client)
    _login(client, "worker")
    assert client.get("/admin/audit").status_code == 403
