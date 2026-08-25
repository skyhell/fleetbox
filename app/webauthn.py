"""Passkeys (WebAuthn) — a thin wrapper around py_webauthn.

Keeps the ceremony details (relying-party identity, the options every ceremony
must carry, base64url encoding) in one place so the router reads as a flow
rather than as protocol plumbing.

Two invariants hold for every ceremony here:

* **User verification is required.** A passkey only counts once the
  authenticator has verified the human — PIN, fingerprint, face. That is what
  makes a single tap a genuine two-factor login (possession + verification).
* **Credentials are discoverable** (``resident_key=required``), which is what
  allows the login page to work without a username: the authenticator itself
  tells the browser which account is being used.

Note that ``app/webauthn.py`` imports the third-party ``webauthn`` package —
absolute imports mean the module does not shadow it.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import settings

RP_NAME = "FleetBox"


@dataclass(frozen=True)
class RelyingParty:
    """The identity the browser checks a passkey against."""

    rp_id: str
    origin: str


@dataclass(frozen=True)
class RegisteredCredential:
    """A verified enrollment, in the shape the database stores it."""

    credential_id: str  # base64url
    public_key: str  # base64url COSE key
    sign_count: int
    aaguid: str | None


@dataclass(frozen=True)
class AuthenticatedCredential:
    """A verified login."""

    credential_id: str  # base64url
    new_sign_count: int


def relying_party(request: Request) -> RelyingParty:
    """Resolve the relying-party id and expected origin.

    Explicit settings win; otherwise both are derived from ``base_url``, and
    failing that from the request itself — which is what makes
    ``http://localhost:8000`` work in development with no configuration at all.

    Deriving from the request is safe against Host-header games: the browser
    refuses to create or use a credential whose ``rp_id`` does not match the
    page it is on, so a forged host yields a failed ceremony, never a credential
    usable elsewhere. Behind a reverse proxy, set the settings explicitly
    anyway — it is one fewer thing depending on correct proxy headers.
    """
    origin = settings.webauthn_origin or settings.base_url
    if not origin:
        origin = str(request.base_url).rstrip("/")
    origin = origin.rstrip("/")

    rp_id = settings.webauthn_rp_id
    if not rp_id:
        # Host without scheme, port or path.
        rp_id = origin.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return RelyingParty(rp_id=rp_id, origin=origin)


def _selection() -> AuthenticatorSelectionCriteria:
    return AuthenticatorSelectionCriteria(
        resident_key=ResidentKeyRequirement.REQUIRED,
        user_verification=UserVerificationRequirement.REQUIRED,
    )


def begin_registration(
    request: Request,
    *,
    user_id: int,
    user_name: str,
    existing_credential_ids: list[str],
) -> tuple[str, str]:
    """Return ``(options_json, challenge_b64url)`` for enrolling a new passkey.

    ``existing_credential_ids`` are excluded so an authenticator that already
    holds a passkey for this account says so instead of silently making a
    second one.
    """
    rp = relying_party(request)
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=RP_NAME,
        user_id=str(user_id).encode("utf-8"),
        user_name=user_name,
        user_display_name=user_name,
        authenticator_selection=_selection(),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid))
            for cid in existing_credential_ids
        ],
    )
    return options_to_json(options), bytes_to_base64url(options.challenge)


def finish_registration(
    request: Request, credential: str, challenge: str
) -> RegisteredCredential:
    """Verify an enrollment response. Raises on any mismatch."""
    rp = relying_party(request)
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(challenge),
        expected_rp_id=rp.rp_id,
        expected_origin=rp.origin,
        require_user_verification=True,
    )
    return RegisteredCredential(
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count,
        aaguid=verified.aaguid or None,
    )


def begin_authentication(request: Request) -> tuple[str, str]:
    """Return ``(options_json, challenge_b64url)`` for a passwordless login.

    ``allow_credentials`` stays empty on purpose: the authenticator picks the
    passkey, so the server never has to be told who is logging in beforehand —
    and cannot be probed for which accounts exist.
    """
    rp = relying_party(request)
    options = generate_authentication_options(
        rp_id=rp.rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(options), bytes_to_base64url(options.challenge)


def finish_authentication(
    request: Request,
    credential: str,
    challenge: str,
    *,
    public_key: str,
    sign_count: int,
) -> AuthenticatedCredential:
    """Verify a login response against a stored credential. Raises on mismatch."""
    rp = relying_party(request)
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(challenge),
        expected_rp_id=rp.rp_id,
        expected_origin=rp.origin,
        credential_public_key=base64url_to_bytes(public_key),
        credential_current_sign_count=sign_count,
        require_user_verification=True,
    )
    return AuthenticatedCredential(
        credential_id=bytes_to_base64url(verified.credential_id),
        new_sign_count=verified.new_sign_count,
    )
