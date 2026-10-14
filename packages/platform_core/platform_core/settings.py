"""Settings shared by every service, read from the single platform .env.

Services never load a .env file themselves: Docker Compose injects
``platform/.env`` through ``env_file``, and local runs export it from the
Makefile. Module-specific settings stay in each service and only add aliases.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    platform_env: str = Field(default="dev")
    platform_public_url: str = Field(default="http://localhost:8080")
    platform_cors_origins: str = Field(default="http://localhost:8080")
    platform_log_level: str = Field(default="INFO")

    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="platform")
    postgres_user: str = Field(default="platform")
    postgres_password: str = Field(default="")
    postgres_pool_min: int = Field(default=2)
    postgres_pool_max: int = Field(default=15)

    storage_backend: str = Field(default="local")
    storage_local_root: str = Field(default="/data/storage")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.platform_cors_origins.split(",") if o.strip()]

    @property
    def public_url(self) -> str:
        return self.platform_public_url.rstrip("/")


@lru_cache
def get_common_settings() -> CommonSettings:
    return CommonSettings()
