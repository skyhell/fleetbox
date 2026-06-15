"""Command-line utilities for FleetBox.

Usage::

    python -m app.cli init-db
    python -m app.cli create-admin --username admin --email a@b.c --password secret
    python -m app.cli send-reminders [--dry-run]
    python -m app.cli serve
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import User
from app.security import hash_password


def _cmd_init_db(args: argparse.Namespace) -> int:
    init_db()
    print("Database initialized.")
    if args.with_admin:
        return _cmd_create_admin(args)
    return 0


def _cmd_create_admin(args: argparse.Namespace) -> int:
    username = args.username or input("Admin username: ").strip()
    email = args.email or input("Admin email: ").strip()
    password = args.password or getpass.getpass("Admin password: ")

    if not username or not email or not password:
        print("username, email and password are required", file=sys.stderr)
        return 1

    init_db()
    db = SessionLocal()
    try:
        exists = (
            db.query(User)
            .filter((User.email == email) | (User.username == username))
            .first()
        )
        if exists:
            print(f"User '{username}' / '{email}' already exists.", file=sys.stderr)
            return 1
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            is_admin=True,
            locale=settings.default_locale,
        )
        db.add(user)
        db.commit()
        print(f"Created admin user '{username}'.")
    finally:
        db.close()
    return 0


def _cmd_disable_2fa(args: argparse.Namespace) -> int:
    """Recovery: turn off 2FA for a user who lost their authenticator."""
    identifier = args.username or args.email or input("Username or email: ").strip()
    init_db()
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter((User.username == identifier) | (User.email == identifier))
            .first()
        )
        if user is None:
            print(f"No user matching '{identifier}'.", file=sys.stderr)
            return 1
        user.totp_secret = None
        user.totp_enabled = False
        db.commit()
        print(f"Disabled 2FA for '{user.username}'.")
    finally:
        db.close()
    return 0


def _cmd_send_reminders(args: argparse.Namespace) -> int:
    """Email each opted-in user a digest of due services and seasonal tyre swaps.

    Meant to be run periodically (cron / systemd timer). With ``--dry-run`` it
    prints what would be sent without contacting an SMTP server.
    """
    from app.mailer import send_email
    from app.reminders import collect_for_user, render_email

    init_db()
    if not settings.smtp_configured and not args.dry_run:
        print(
            "SMTP is not configured (set FLEETBOX_SMTP_HOST). "
            "Use --dry-run to preview without sending.",
            file=sys.stderr,
        )
        return 1

    db = SessionLocal()
    sent = failed = 0
    try:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True), User.notify_email.is_(True))
            .all()
        )
        for user in users:
            if not user.email:
                continue
            reminders = collect_for_user(db, user)
            if not reminders:
                continue
            subject, body = render_email(reminders, user.locale, settings.base_url)
            if args.dry_run:
                print(f"[dry-run] {user.email}: {len(reminders)} reminder(s)")
                for r in reminders:
                    print(f"    - [{r.vehicle}] {r.title}: {r.detail}")
                continue
            try:
                send_email(user.email, subject, body)
                sent += 1
            except Exception as exc:  # noqa: BLE001 - report and continue
                failed += 1
                print(f"Failed to email {user.email}: {exc}", file=sys.stderr)
    finally:
        db.close()

    if not args.dry_run:
        print(f"Sent {sent} reminder email(s); {failed} failed.")
    return 1 if failed else 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        # Honor X-Forwarded-* from a trusted reverse proxy (nginx/Caddy).
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips or settings.forwarded_allow_ips,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleetbox", description="FleetBox management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Create database tables")
    p_init.add_argument("--with-admin", action="store_true", help="Also create an admin user")
    p_init.add_argument("--username")
    p_init.add_argument("--email")
    p_init.add_argument("--password")
    p_init.set_defaults(func=_cmd_init_db)

    p_admin = sub.add_parser("create-admin", help="Create an administrator account")
    p_admin.add_argument("--username")
    p_admin.add_argument("--email")
    p_admin.add_argument("--password")
    p_admin.set_defaults(func=_cmd_create_admin)

    p_2fa = sub.add_parser("disable-2fa", help="Disable 2FA for a user (account recovery)")
    p_2fa.add_argument("--username")
    p_2fa.add_argument("--email")
    p_2fa.set_defaults(func=_cmd_disable_2fa)

    p_rem = sub.add_parser(
        "send-reminders", help="Email due-service and seasonal tyre reminders"
    )
    p_rem.add_argument(
        "--dry-run", action="store_true", help="Print what would be sent, send nothing"
    )
    p_rem.set_defaults(func=_cmd_send_reminders)

    p_serve = sub.add_parser("serve", help="Run the web server")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument(
        "--forwarded-allow-ips",
        default=None,
        help="Trusted proxy IPs for X-Forwarded-* headers ('*' to trust all). "
        "Defaults to FLEETBOX_FORWARDED_ALLOW_IPS / 127.0.0.1.",
    )
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
