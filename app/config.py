"""Application configuration.

All credentials are read from environment variables (or a local ``.env`` file
that is never committed). Nothing secret is hardcoded in the source code.
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -----------------------------------------------------------
    app_name: str = "Automated Multi-Platform Posting API"
    log_level: str = "INFO"
    # Timezone used for the "date" / "time" fields of each posting result.
    app_timezone: str = "Asia/Kolkata"
    # Maximum seconds a single platform may take (publish + public check).
    platform_timeout_seconds: float = 20.0
    # Comma separated list of platform keys to use. Empty = all platforms.
    enabled_platforms: str = ""

    # --- Bluesky (AT Protocol) ---------------------------------------------
    bluesky_handle: Optional[str] = None
    bluesky_app_password: Optional[SecretStr] = None
    bluesky_service_url: str = "https://bsky.social"

    # --- Mastodon ------------------------------------------------------------
    mastodon_instance_url: Optional[str] = None
    mastodon_access_token: Optional[SecretStr] = None

    # --- Telegram (public channel via Bot API) -------------------------------
    telegram_bot_token: Optional[SecretStr] = None
    telegram_channel_username: Optional[str] = None  # e.g. "@my_channel"

    # --- GitHub Gist ---------------------------------------------------------
    github_token: Optional[SecretStr] = None

    # --- DEV Community (Forem API) -------------------------------------------
    devto_api_key: Optional[SecretStr] = None

    # --- Discord (channel webhook) -------------------------------------------
    discord_webhook_url: Optional[SecretStr] = None

    @field_validator("mastodon_instance_url", "bluesky_service_url")
    @classmethod
    def normalize_base_url(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        """Accept "mastodon.social" as well as "https://mastodon.social/"."""
        if not value or not value.strip():
            return "https://bsky.social" if info.field_name == "bluesky_service_url" else None
        value = value.strip().rstrip("/")
        if value.startswith("http://"):
            raise ValueError("Instance URL must use https://")
        return value if value.startswith("https://") else f"https://{value}"

    @property
    def enabled_platform_keys(self) -> List[str]:
        return [p.strip().lower() for p in self.enabled_platforms.split(",") if p.strip()]

    def secret_values(self) -> List[str]:
        """All configured secret values - used to redact them from error text."""
        values: List[str] = []
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if isinstance(value, SecretStr):
                raw = value.get_secret_value()
                if raw:
                    values.append(raw)
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
