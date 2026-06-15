"""Symmetric encryption for secrets stored at rest (e.g. TOTP seeds).

The Fernet key is derived from ``FLEETBOX_SECRET_KEY`` so no extra key material
needs to be managed. Note: rotating the secret key invalidates previously
encrypted values, so users would need to re-enroll their 2FA.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str | None) -> str | None:
    """Decrypt a value, returning ``None`` if it cannot be decrypted."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
