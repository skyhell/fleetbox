"""Tests for the security hardening pack: password change, TOTP replay
protection, recovery codes, POST-only logout and response headers."""

from __future__ import annotations

import re

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    html = client.get(url).text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"no CSRF token found on {url}"
    return match.group(1)


def _register(client, username: str, email: str) -> None:
    token = _csrf(client, "/register")
    client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _logout(client) -> None:
    client.post(
        "/logout",
        data={"csrf_token": _csrf(client, "/dashboard")},
        follow_redirects=False,
    )


def _login(client, identifier: str, password: str):
    token = _csrf(client, "/login")
    return client.post(
        "/login",
        data={"identifier": identifier, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


# --- Password change ---------------------------------------------------------


def test_password_change_flow(client):
    _register(client, "alice", "alice@example.com")

    # Wrong current password is rejected.
    token = _csrf(client, "/account/security")
    resp = client.post(
        "/account/password",
        data={"current_password": "nope", "new_password": "NewSecret456",
              "new_password_repeat": "NewSecret456", "csrf_token": token},
    )
    assert (
        "aktuelle Passwort ist falsch" in resp.text
        or "current password is incorrect" in resp.text
    )

    # Mismatching repetition is rejected.
    token = _csrf(client, "/account/security")
    resp = client.post(
        "/account/password",
        data={"current_password": PASSWORD, "new_password": "NewSecret456",
              "new_password_repeat": "Different789", "csrf_token": token},
    )
    assert "stimmen nicht überein" in resp.text or "do not match" in resp.text

    # Too-short new password is rejected.
    token = _csrf(client, "/account/security")
    resp = client.post(
        "/account/password",
        data={"current_password": PASSWORD, "new_password": "abc",
              "new_password_repeat": "abc", "csrf_token": token},
    )
    assert "mindestens" in resp.text or "at least" in resp.text

    # Valid change succeeds; only the new password logs in afterwards.
    token = _csrf(client, "/account/security")
    resp = client.post(
        "/account/password",
        data={"current_password": PASSWORD, "new_password": "NewSecret456",
              "new_password_repeat": "NewSecret456", "csrf_token": token},
    )
    assert "geändert" in resp.text or "changed" in resp.text

    _logout(client)
    assert _login(client, "alice", PASSWORD).status_code == 200  # rejected, re-renders
    assert _login(client, "alice", "NewSecret456").status_code == 303


# --- Logout ------------------------------------------------------------------


def test_logout_requires_post(client):
    _register(client, "bob", "bob@example.com")

    # A plain GET (prefetch, old bookmark) must NOT end the session.
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get("/dashboard").status_code == 200

    # POST with CSRF token logs out.
    _logout(client)
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)


# --- Response headers --------------------------------------------------------


def test_hardening_headers_present(client):
    resp = client.get("/login")
    assert "camera=()" in resp.headers.get("Permissions-Policy", "")
    assert resp.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert resp.headers.get("Cross-Origin-Resource-Policy") == "same-origin"


# --- 2FA: replay protection & recovery codes ---------------------------------


def _enroll_2fa(client) -> tuple[str, list[str], str]:
    """Enable 2FA via the real endpoints; returns (secret, recovery_codes, used_code)."""
    import pyotp

    token = _csrf(client, "/account/security")
    setup = client.post("/account/2fa/begin", data={"csrf_token": token}).text
    secret = re.search(r"<code[^>]*>([A-Z2-7]{16,})</code>", setup).group(1)

    code = pyotp.TOTP(secret).now()
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', setup)
    confirmed = client.post(
        "/account/2fa/enable",
        data={"code": code, "csrf_token": token_match.group(1)},
    ).text
    codes = re.findall(r"<code>([a-z2-9]{5}-[a-z2-9]{5})</code>", confirmed)
    assert len(codes) == 8, "recovery codes must be shown once after enrollment"
    return secret, codes, code


def test_totp_replay_rejected_and_recovery_code_works(client):
    _register(client, "carol", "carol@example.com")
    secret, recovery_codes, used_code = _enroll_2fa(client)
    _logout(client)

    # Password login defers to the 2FA challenge.
    assert _login(client, "carol", PASSWORD).headers["location"] == "/login/2fa"

    # Replaying the code that was already consumed during enrollment fails.
    token = _csrf(client, "/login/2fa")
    replay = client.post(
        "/login/2fa", data={"code": used_code, "csrf_token": token}, follow_redirects=False
    )
    assert replay.status_code == 200  # re-rendered with error, no login

    # A recovery code completes the login instead.
    token = _csrf(client, "/login/2fa")
    ok = client.post(
        "/login/2fa",
        data={"code": recovery_codes[0], "csrf_token": token},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert client.get("/dashboard").status_code == 200


def test_recovery_codes_are_single_use(client):
    _register(client, "dave", "dave@example.com")
    _, recovery_codes, _ = _enroll_2fa(client)
    _logout(client)

    # First use of a recovery code works.
    _login(client, "dave", PASSWORD)
    token = _csrf(client, "/login/2fa")
    first = client.post(
        "/login/2fa", data={"code": recovery_codes[0], "csrf_token": token},
        follow_redirects=False,
    )
    assert first.status_code == 303
    _logout(client)

    # The same code is burned; a different one still works.
    _login(client, "dave", PASSWORD)
    token = _csrf(client, "/login/2fa")
    burned = client.post(
        "/login/2fa", data={"code": recovery_codes[0], "csrf_token": token},
        follow_redirects=False,
    )
    assert burned.status_code == 200
    token = _csrf(client, "/login/2fa")
    other = client.post(
        "/login/2fa", data={"code": recovery_codes[1], "csrf_token": token},
        follow_redirects=False,
    )
    assert other.status_code == 303
