"""Two-factor authentication helpers (TOTP, RFC 6238).

Uses ``pyotp`` for the time-based one-time-password logic and ``qrcode`` to
render an enrollment QR code as an inline SVG (no Pillow dependency).
"""

from __future__ import annotations

import io

import pyotp
import qrcode
import qrcode.image.svg

ISSUER = "FleetBox"


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    """Build the ``otpauth://`` URI for authenticator apps."""
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=ISSUER)


def verify_code(secret: str | None, code: str) -> bool:
    """Verify a 6-digit code, allowing for ±1 time step of clock drift."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def qr_svg(data: str) -> str:
    """Render ``data`` as an inline SVG QR code string."""
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")
