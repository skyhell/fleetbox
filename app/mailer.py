"""Minimal SMTP email sending for reminder notifications.

Uses only the standard library (``smtplib`` + ``email``) — no extra dependency.
Email is optional: nothing is sent unless ``FLEETBOX_SMTP_HOST`` is configured.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises ``RuntimeError`` if SMTP is unconfigured."""
    if not settings.smtp_configured:
        raise RuntimeError("SMTP is not configured (set FLEETBOX_SMTP_HOST).")

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user or "fleetbox@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if settings.smtp_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as s:
            _authenticate_and_send(s, msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            if settings.smtp_starttls:
                s.starttls(context=ssl.create_default_context())
            _authenticate_and_send(s, msg)


def _authenticate_and_send(server: smtplib.SMTP, msg: EmailMessage) -> None:
    if settings.smtp_user:
        server.login(settings.smtp_user, settings.smtp_password)
    server.send_message(msg)
