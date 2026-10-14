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

    storage_backend: str = Field(default="local")  # local | s3
    storage_local_root: str = Field(default="/data/storage")  # local files, or the S3 cache

    s3_endpoint_url: str = Field(default="")
    s3_region: str = Field(default="us-east-1")
    s3_bucket: str = Field(default="")
    s3_prefix: str = Field(default="")
    s3_access_key_id: str = Field(default="")
    s3_secret_access_key: str = Field(default="")
    s3_addressing_style: str = Field(default="path")  # path | virtual
    s3_verify_ssl: bool = Field(default=True)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.platform_cors_origins.split(",") if o.strip()]

    @property
    def public_url(self) -> str:
        return self.platform_public_url.rstrip("/")


@lru_cache
def get_common_settings() -> CommonSettings:
    return CommonSettings()


_WEAK = ("change-me", "change-me-to-at-least-32-random-characters", "")


def startup_report(service: str) -> dict[str, str]:
    """Log what a service loaded (secrets masked); refuse weak secrets in production.

    Called from each service's startup so configuration mistakes show up in
    ``docker compose logs`` instead of as odd runtime errors.
    """
    import logging
    import os

    s = get_common_settings()
    report = {
        "service": service,
        "env": s.platform_env,
        "postgres": f"{s.postgres_user}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}",
        "auth_mode": os.environ.get("AUTH_MODE", "mock"),
        "storage": s.storage_backend
        + (f" ({s.s3_endpoint_url or 'aws'} bucket={s.s3_bucket}{'/' + s.s3_prefix if s.s3_prefix else ''})" if s.storage_backend == "s3" else f" ({s.storage_local_root})"),
    }
    logging.getLogger("platform.config").info("startup config: %s", report)
    print(f"[platform] startup config: {report}", flush=True)
    if s.platform_env == "production":
        weak = [
            name
            for name in ("POSTGRES_PASSWORD", "AUTH_JWT_SECRET", "DESIGNER_SHARED_SECRET")
            if os.environ.get(name, "") in _WEAK
        ]
        if weak:
            raise RuntimeError(f"Refusing to start in production with default secrets: {weak}")
    return report
