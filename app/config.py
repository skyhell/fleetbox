"""Application configuration, loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# Content types accepted for document/photo uploads. Deliberately narrow:
# raster images render inline safely under our CSP, and PDFs are served as a
# download. SVG/HTML are excluded because they can carry active content.
ALLOWED_UPLOAD_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

# Sentinel value used as the default secret key. The app refuses to start in a
# production posture (secure cookies on) while this is still in place.
INSECURE_DEFAULT_SECRET_KEY = "insecure-development-key-change-me"  # nosec B105


class Settings(BaseSettings):
    """Runtime configuration.

    All values can be overridden via environment variables prefixed with
    ``FLEETBOX_`` (see ``.env.example``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FLEETBOX_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = INSECURE_DEFAULT_SECRET_KEY
    database_url: str = "sqlite:///./data/fleetbox.db"

    host: str = "0.0.0.0"
    port: int = 8000

    default_locale: str = "de"
    supported_locales: tuple[str, ...] = ("de", "en")

    allow_registration: bool = True
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days

    # Set true when served over HTTPS (e.g. behind an nginx/Caddy reverse proxy)
    # so the session cookie gets the `Secure` flag. Keep false for plain-HTTP dev.
    secure_cookies: bool = False

    # Trusted reverse-proxy IP(s) for uvicorn's X-Forwarded-* handling.
    # Comma-separated list or "*". Default trusts only localhost.
    forwarded_allow_ips: str = "127.0.0.1"

    # Minimum password length enforced on registration / user creation.
    min_password_length: int = 8

    # Brute-force protection for login and 2FA (per client IP).
    rate_limit_max_attempts: int = 10
    rate_limit_window_seconds: int = 300

    # Document/photo uploads: where files are stored and the per-file size cap.
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MiB

    # Link target for the "Documentation" entry in the UI footer.
    docs_url: str = "https://github.com/skyhell/fleetbox/tree/main/docs"

    # Public base URL (e.g. https://fleetbox.example.com), used to build links in
    # reminder emails. Leave empty to omit the link.
    base_url: str = ""

    # Email (SMTP) for reminder notifications. Reminders are only sent when a host
    # is configured, by the `fleetbox send-reminders` command (run from cron or a
    # systemd timer).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # falls back to smtp_user
    smtp_starttls: bool = True
    smtp_ssl: bool = False  # implicit TLS (usually port 465); overrides STARTTLS

    # Seasonal tyre-change reminder months (1-12). Defaults follow the German
    # "O bis O" rule of thumb: switch to winter tyres in October, summer in April.
    winter_tire_month: int = 10
    summer_tire_month: int = 4

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)

    @property
    def upload_path(self) -> Path:
        """Absolute path to the upload directory (created on first use)."""
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    @property
    def uses_default_secret_key(self) -> bool:
        return self.secret_key == INSECURE_DEFAULT_SECRET_KEY

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
