"""Admin user editing: profile changes, password reset, self-demotion guard."""

from __future__ import annotations

import re

PASSWORD = "Secret123"


def _csrf(client, url: str) -> str:
    resp = client.get(url)
    html = resp.text
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"no CSRF token found on {url} (status {resp.status_code}): {html[:300]!r}"
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


def _add_user(client, username: str, email: str, password: str = PASSWORD):
    token = _csrf(client, "/admin/users")
    return client.post(
        "/admin/users",
        data={"username": username, "email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _setup_admin_and_user(client):
    """First registered user is admin; a second plain user is added via admin."""
    _register(client, "admin", "admin@example.com")
    _add_user(client, "worker", "worker@example.com")


def test_users_list_has_edit_links(client):
    _setup_admin_and_user(client)
    html = client.get("/admin/users").text
    assert re.search(r'href="/admin/users/\d+/edit"', html)


def test_edit_form_is_prefilled(client):
    _setup_admin_and_user(client)
    resp = client.get("/admin/users/2/edit")
    assert resp.status_code == 200
    assert 'value="worker"' in resp.text
    assert 'value="worker@example.com"' in resp.text


def test_admin_edits_profile_and_resets_password(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/2/edit")
    resp = client.post(
        "/admin/users/2/edit",
        data={
            "username": "worker2",
            "email": "worker2@example.com",
            "password": "Fresh12345",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/users"

    _logout(client)
    # Old password no longer works, the new one does — under the new username.
    assert _login(client, "worker2", PASSWORD).status_code == 200  # error re-render
    resp = _login(client, "worker2", "Fresh12345")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"


def test_empty_password_keeps_current_one(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/2/edit")
    resp = client.post(
        "/admin/users/2/edit",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    _logout(client)
    resp = _login(client, "worker")
    assert resp.status_code == 303


def test_short_password_is_rejected(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/2/edit")
    resp = client.post(
        "/admin/users/2/edit",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": "abc",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200  # re-rendered with an error
    assert "alert-error" in resp.text

    _logout(client)
    assert _login(client, "worker").status_code == 303  # old password still valid


def test_edit_password_mismatch_is_rejected(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/2/edit")
    resp = client.post(
        "/admin/users/2/edit",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": "Fresh12345",
            "password_repeat": "Different1",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "alert-error" in resp.text

    _logout(client)
    assert _login(client, "worker").status_code == 303  # old password still valid


def test_add_user_password_mismatch_is_rejected(client):
    _register(client, "admin", "admin@example.com")
    token = _csrf(client, "/admin/users")
    resp = client.post(
        "/admin/users",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": PASSWORD,
            "password_repeat": PASSWORD + "x",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "alert-error" in resp.text


def test_duplicate_username_is_rejected(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/2/edit")
    resp = client.post(
        "/admin/users/2/edit",
        data={
            "username": "admin",
            "email": "worker@example.com",
            "password": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "alert-error" in resp.text


def test_admin_cannot_demote_self(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/1/edit")
    resp = client.post(
        "/admin/users/1/edit",
        data={
            "username": "admin",
            "email": "admin@example.com",
            "password": "",
            # no is_admin field — would demote anyone else
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Still an admin: the user management page keeps working.
    assert client.get("/admin/users").status_code == 200


def test_admin_can_promote_and_demote_others(client):
    _setup_admin_and_user(client)
    token = _csrf(client, "/admin/users/2/edit")
    resp = client.post(
        "/admin/users/2/edit",
        data={
            "username": "worker",
            "email": "worker@example.com",
            "password": "",
            "is_admin": "1",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    _logout(client)
    _login(client, "worker")
    assert client.get("/admin/users").status_code == 200


def test_non_admin_cannot_edit_users(client):
    _setup_admin_and_user(client)
    _logout(client)
    _login(client, "worker")
    assert client.get("/admin/users/1/edit").status_code == 403
    token = _csrf(client, "/dashboard")
    resp = client.post(
        "/admin/users/1/edit",
        data={
            "username": "admin",
            "email": "admin@example.com",
            "password": "Hacked1234",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_edit_unknown_user_is_404(client):
    _setup_admin_and_user(client)
    assert client.get("/admin/users/999/edit").status_code == 404
