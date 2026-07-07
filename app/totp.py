"""Two-factor authentication helpers (TOTP, RFC 6238).

Uses ``pyotp`` for the time-based one-time-password logic and ``qrcode`` to
render an enrollment QR code as an inline SVG (no Pillow dependency).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg

ISSUER = "FleetBox"

# One-time recovery codes: 8 codes of 10 characters, drawn from an alphabet
# without visually ambiguous characters (no 0/o, 1/l/i).
RECOVERY_CODE_COUNT = 8
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    """Build the ``otpauth://`` URI for authenticator apps."""
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=ISSUER)


def verify_code_step(secret: str | None, code: str, last_used: int | None = None) -> int | None:
    """Verify a 6-digit code and return its time step, or ``None``.

    Allows ±1 time step of clock drift. Passing the last accepted step via
    ``last_used`` rejects codes for that step or earlier, so a sniffed code
    cannot be replayed within its validity window.
    """
    if not secret or not code:
        return None
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now = time.time()
    for offset in (0, -1, 1):
        step_time = now + offset * totp.interval
        if hmac.compare_digest(totp.at(step_time), code):
            step = int(step_time) // totp.interval
            if last_used is not None and step <= last_used:
                return None
            return step
    return None


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Return fresh one-time recovery codes, formatted ``xxxxx-xxxxx``."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    """Hash a recovery code for storage/lookup (codes are high-entropy)."""
    normalized = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def qr_svg(data: str) -> str:
    """Render ``data`` as an inline SVG QR code string."""
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")
