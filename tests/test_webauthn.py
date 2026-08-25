"""Tests for passkeys (WebAuthn).

The cryptography itself is py_webauthn's job and is exercised for real by the
Playwright smoke test (`scripts/verify_e2e.py`, virtual authenticator). What is
worth testing here is everything *around* it: that a ceremony needs a live
challenge, that the challenge is good exactly once, that a passkey login is held
to the same rules as a password login (lockout, rate limit, audit trail), and
that one user can never touch another's passkey.

The two verification calls are therefore stubbed — they are the seam between
FleetBox and the library.
"""

from __future__ import annotations

import re

import pytest

from app import webauthn as ceremony
from app.config import settings

PASSWORD = "Secret123"

# A syntactically valid base64url credential, standing in for a real one.
CREDENTIAL_ID = "dGVzdC1jcmVkZW50aWFsLWlk"
PUBLIC_KEY = "cHVibGljLWtleQ"


def _csrf(client, url: str = "/login") -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(url).text)
    assert match, f"no CSRF token on {url}"
    return match.group(1)


def _register_user(client, username: str, email: str) -> None:
    token = _csrf(client, "/register")
    client.post(
        "/register",
        data={"username": username, "email": email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def _post_json(client, url: str, body: dict | None = None, *, page: str = "/account/security"):
    """POST JSON the way the browser does: CSRF token in the header."""
    return client.post(
        url,
        json=body or {},
        headers={"X-CSRF-Token": _csrf(client, page)},
        follow_redirects=False,
    )


def _client_credential(credential_id: str = CREDENTIAL_ID) -> dict:
    """The shape app.js posts back; the stub makes its contents irrelevant."""
    return {
        "id": credential_id,
        "rawId": credential_id,
        "type": "public-key",
        "response": {"clientDataJSON": "e30", "attestationObject": "e30",
                     "transports": ["internal"]},
    }


@pytest.fixture()
def stub_registration(monkeypatch):
    """Accept any enrollment, reporting the credential the caller asked for."""

    def _stub(credential_id: str = CREDENTIAL_ID, sign_count: int = 0):
        def fake(request, credential, challenge):
            return ceremony.RegisteredCredential(
                credential_id=credential_id,
                public_key=PUBLIC_KEY,
                sign_count=sign_count,
                aaguid="00000000-0000-0000-0000-000000000000",
            )

        monkeypatch.setattr(ceremony, "finish_registration", fake)

    return _stub


@pytest.fixture()
def stub_authentication(monkeypatch):
    """Accept any assertion, reporting the given signature counter."""

    def _stub(new_sign_count: int = 1, fail: bool = False):
        def fake(request, credential, challenge, *, public_key, sign_count):
            if fail:
                raise ValueError("signature mismatch")
            return ceremony.AuthenticatedCredential(
                credential_id=CREDENTIAL_ID, new_sign_count=new_sign_count
            )

        monkeypatch.setattr(ceremony, "finish_authentication", fake)

    return _stub


def _enroll(
    client, stub_registration, *,
    credential_id: str = CREDENTIAL_ID, name: str = "Yubikey",
):
    """Run a full (stubbed) enrollment for the logged-in user."""
    stub_registration(credential_id)
    assert _post_json(client, "/webauthn/register/begin").status_code == 200
    resp = _post_json(
        client,
        "/webauthn/register/finish",
        {"name": name, "credential": _client_credential(credential_id)},
    )
    assert resp.status_code == 200, resp.text
    return resp


# --- CSRF on JSON endpoints ---------------------------------------------------


def test_json_post_without_the_csrf_header_is_rejected(client):
    _register_user(client, "alice", "alice@example.com")
    resp = client.post("/webauthn/register/begin", json={}, follow_redirects=False)
    assert resp.status_code == 403


def test_json_post_with_the_csrf_header_is_accepted(client):
    _register_user(client, "bob", "bob@example.com")
    assert _post_json(client, "/webauthn/register/begin").status_code == 200


# --- Enrollment ---------------------------------------------------------------


def test_registration_options_are_returned(client):
    _register_user(client, "carol", "carol@example.com")
    options = _post_json(client, "/webauthn/register/begin").json()
    assert options["rp"]["id"]
    assert options["challenge"]
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["authenticatorSelection"]["residentKey"] == "required"


def test_registration_needs_a_challenge(client, stub_registration):
    _register_user(client, "dave", "dave@example.com")
    stub_registration()
    # No /begin first: there is nothing in the session to verify against.
    resp = _post_json(
        client, "/webauthn/register/finish", {"credential": _client_credential()}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]


def test_registration_stores_the_passkey(client, stub_registration):
    _register_user(client, "erin", "erin@example.com")
    _enroll(client, stub_registration, name="Handy")

    from app.database import SessionLocal
    from app.models import User, WebAuthnCredential

    db = SessionLocal()
    try:
        credential = db.query(WebAuthnCredential).one()
        assert credential.credential_id == CREDENTIAL_ID
        assert credential.public_key == PUBLIC_KEY
        assert credential.name == "Handy"
        assert credential.user_id == db.query(User).filter_by(username="erin").one().id
    finally:
        db.close()

    page = client.get("/account/security").text
    assert "Handy" in page
    assert "Passkey hinzugefügt." in page  # the flash from the redirect-less finish


def test_challenge_is_single_use(client, stub_registration):
    _register_user(client, "frank", "frank@example.com")
    _enroll(client, stub_registration)

    # Replaying the same finish without a new /begin must not enroll twice.
    resp = _post_json(
        client, "/webauthn/register/finish", {"credential": _client_credential()}
    )
    assert resp.status_code == 400


def test_the_same_credential_cannot_be_registered_twice(client, stub_registration):
    _register_user(client, "grace", "grace@example.com")
    _enroll(client, stub_registration)

    _post_json(client, "/webauthn/register/begin")
    resp = _post_json(
        client,
        "/webauthn/register/finish",
        {"name": "again", "credential": _client_credential()},
    )
    assert resp.status_code == 400
    assert "bereits" in resp.json()["error"] or "already" in resp.json()["error"]


# --- Ownership ----------------------------------------------------------------


def test_deleting_a_foreign_passkey_is_404(client, stub_registration):
    _register_user(client, "owner", "owner@example.com")
    _enroll(client, stub_registration)

    from app.database import SessionLocal
    from app.models import WebAuthnCredential

    db = SessionLocal()
    try:
        credential_pk = db.query(WebAuthnCredential).one().id
    finally:
        db.close()

    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")},
                follow_redirects=False)
    _register_user(client, "intruder", "intruder@example.com")

    resp = client.post(
        f"/webauthn/{credential_pk}/delete",
        data={"csrf_token": _csrf(client, "/account/security")},
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_owner_can_delete_their_passkey(client, stub_registration):
    _register_user(client, "heidi", "heidi@example.com")
    _enroll(client, stub_registration)

    from app.database import SessionLocal
    from app.models import WebAuthnCredential

    db = SessionLocal()
    try:
        credential_pk = db.query(WebAuthnCredential).one().id
    finally:
        db.close()

    resp = client.post(
        f"/webauthn/{credential_pk}/delete",
        data={"csrf_token": _csrf(client, "/account/security")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Passkey entfernt." in client.get("/account/security").text


# --- Passwordless login -------------------------------------------------------


def _logout(client):
    client.post("/logout", data={"csrf_token": _csrf(client, "/dashboard")},
                follow_redirects=False)


def _login_with_passkey(client):
    assert _post_json(client, "/webauthn/login/begin", page="/login").status_code == 200
    return _post_json(
        client,
        "/webauthn/login/finish",
        {"credential": _client_credential()},
        page="/login",
    )


def test_passkey_login_establishes_a_session(client, stub_registration, stub_authentication):
    _register_user(client, "ivan", "ivan@example.com")
    _enroll(client, stub_registration)
    _logout(client)
    assert client.get("/dashboard", follow_redirects=False).status_code == 303

    stub_authentication(new_sign_count=1)
    resp = _login_with_passkey(client)
    assert resp.status_code == 200
    assert resp.json()["redirect"] == "/dashboard"
    assert client.get("/dashboard").status_code == 200


def test_passkey_login_records_the_audit_trail(client, stub_registration, stub_authentication):
    _register_user(client, "judy", "judy@example.com")
    _enroll(client, stub_registration)
    _logout(client)
    stub_authentication(new_sign_count=1)
    _login_with_passkey(client)

    page = client.get("/admin/audit").text
    assert "passkey" in page


def test_unknown_credential_is_rejected(client, stub_authentication):
    stub_authentication()
    resp = _login_with_passkey(client)
    assert resp.status_code == 401


def test_failed_signature_is_rejected(client, stub_registration, stub_authentication):
    _register_user(client, "ken", "ken@example.com")
    _enroll(client, stub_registration)
    _logout(client)

    stub_authentication(fail=True)
    assert _login_with_passkey(client).status_code == 401
    # Still logged out.
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_sign_count_regression_is_rejected(client, stub_registration, stub_authentication):
    """A counter that fails to advance is the cloned-authenticator signal."""
    _register_user(client, "laura", "laura@example.com")
    _enroll(client, stub_registration, credential_id=CREDENTIAL_ID)

    from app.database import SessionLocal
    from app.models import WebAuthnCredential

    db = SessionLocal()
    try:
        credential = db.query(WebAuthnCredential).one()
        credential.sign_count = 5
        db.commit()
    finally:
        db.close()

    _logout(client)
    stub_authentication(new_sign_count=5)  # not greater than the stored 5
    assert _login_with_passkey(client).status_code == 401
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_locked_account_cannot_use_a_passkey(client, stub_registration, stub_authentication):
    from datetime import UTC, datetime, timedelta

    _register_user(client, "mike", "mike@example.com")
    _enroll(client, stub_registration)
    _logout(client)

    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username="mike").one()
        user.locked_until = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=15)
        db.commit()
    finally:
        db.close()

    stub_authentication(new_sign_count=1)
    assert _login_with_passkey(client).status_code == 401


def test_deactivated_user_cannot_use_a_passkey(client, stub_registration, stub_authentication):
    _register_user(client, "nina", "nina@example.com")
    _enroll(client, stub_registration)
    _logout(client)

    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username="nina").one()
        user.is_active = False
        db.commit()
    finally:
        db.close()

    stub_authentication(new_sign_count=1)
    assert _login_with_passkey(client).status_code == 401


def test_login_needs_a_challenge(client, stub_registration, stub_authentication):
    _register_user(client, "olga", "olga@example.com")
    _enroll(client, stub_registration)
    _logout(client)

    stub_authentication()
    # Straight to /finish, no /begin.
    resp = _post_json(
        client, "/webauthn/login/finish", {"credential": _client_credential()}, page="/login"
    )
    assert resp.status_code == 400


# --- Admin 2FA policy ---------------------------------------------------------


def test_passkey_satisfies_the_admin_2fa_policy(client, stub_registration, monkeypatch):
    _register_user(client, "boss", "boss@example.com")  # first user -> admin
    monkeypatch.setattr(settings, "require_admin_2fa", True)
    # Without a second factor the admin area redirects to Account security.
    assert client.get("/admin/users", follow_redirects=False).status_code == 303

    _enroll(client, stub_registration)
    assert client.get("/admin/users").status_code == 200
