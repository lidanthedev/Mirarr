"""Configuration management for Mirrarr."""

from pydantic import PositiveInt, field_validator
from functools import lru_cache
from typing import Literal
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlparse


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # TMDB
    tmdb_api_key: str

    # Database
    database_url: str = "sqlite:///./mirrarr.db"

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Provider settings
    provider_timeout: PositiveInt = 60  # Timeout for provider searches in seconds
    preferred_provider: str | None = None  # Provider to prioritize in AUTO selection
    quality_limit: Literal["2160p", "1080p", "720p", "480p", "360p", "240p"] = (
        "2160p"  # Maximum quality to consider in AUTO selection
    )

    # Network settings
    # Proxy configuration in the format http://host:port or socks5://host:port
    proxy: str | None = None

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, v: str | None) -> str | None:
        if v is None:
            return v

        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https", "socks4", "socks5", "socks5h"):
            raise ValueError(
                "Proxy must be a valid URL with scheme http/https/socks4/socks5/socks5h"
            )
        if not parsed.netloc:
            raise ValueError("Proxy must have a host and port")
        return v

    # Authentication credentials used by the Basic Auth middleware
    auth_username: str = ""
    auth_password: SecretStr = SecretStr("")

    # App settings
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
