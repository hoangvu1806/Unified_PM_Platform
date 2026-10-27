import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # No env_file: the single platform/.env is injected by Compose (env_file)
    # or exported by the Makefile for local runs.
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, populate_by_name=True)

    backend_port: int = Field(8282, validation_alias=AliasChoices("DESIGNER_API_PORT", "BACKEND_PORT"))
    cors_origins: str = Field(
        "http://localhost:8080",
        validation_alias=AliasChoices("PLATFORM_CORS_ORIGINS", "CORS_ORIGINS"),
    )

    llm_model: str = Field(validation_alias=AliasChoices("DESIGNER_LLM_MODEL", "LLM_MODEL"))
    designer_model: str = Field("", validation_alias=AliasChoices("DESIGNER_CANVAS_MODEL", "DESIGNER_MODEL"))
    # Designer-specific overrides; an empty value falls back to the shared LLM_*.
    api_key: str = Field("", validation_alias=AliasChoices("DESIGNER_LLM_API_KEY", "API_KEY"))
    base_url: str = Field("", validation_alias=AliasChoices("DESIGNER_LLM_BASE_URL", "BASE_URL"))
    shared_llm_api_key: str = Field("", validation_alias="LLM_API_KEY")
    shared_llm_base_url: str = Field("", validation_alias="LLM_BASE_URL")

    platform_env: str = "dev"
    # Browser origin of the gateway: the design iframe loads vendor scripts from here.
    platform_public_url: str = "http://localhost:8080"
    designer_shared_secret: str = ""
    # One screen = a draft call + at most this many review calls (screenshot + lint → OK / edits).
    designer_review_rounds: int = Field(2, validation_alias="DESIGNER_REVIEW_ROUNDS")
    # Screens after the first (which sets the shell) are built concurrently.
    designer_parallel_screens: int = Field(3, validation_alias="DESIGNER_PARALLEL_SCREENS")
    designer_page_timeout_seconds: int = Field(300, validation_alias="DESIGNER_PAGE_TIMEOUT_SECONDS")
    unsplash_access_key: str = ""
    # A whole screen is one tool call: leave room for it, and keep "thinking" from eating the budget.
    designer_max_output_tokens: int = Field(32000, validation_alias="DESIGNER_MAX_OUTPUT_TOKENS")
    designer_reasoning_effort: str = Field("low", validation_alias="DESIGNER_REASONING_EFFORT")

    @model_validator(mode="after")
    def _fallback_to_shared_llm(self) -> "Settings":
        self.api_key = self.api_key.strip() or self.shared_llm_api_key.strip()
        self.base_url = self.base_url.strip() or self.shared_llm_base_url.strip()
        return self

    @property
    def cleaned_base_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def effective_designer_model(self) -> str:
        return self.designer_model.strip() or self.llm_model

    @property
    def masked_api_key(self) -> str:
        k = self.api_key.strip()
        if len(k) <= 8:
            return "***"
        return f"{k[:6]}...{k[-4:]}"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def api_key_fingerprint(self) -> str:
        """Safe identifier for confirming which key a running process loaded."""
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:12]

    @property
    def postgres_dsn(self) -> str:
        """libpq DSN for the shared platform database (POSTGRES_* in .env)."""
        from platform_core.db import database_url

        return database_url("designer", "libpq")


@lru_cache
def get_settings() -> Settings:
    return Settings()


ASSET_PREFIX = ("designer", "assets")


def _asset_key(asset_id: str) -> str:
    from platform_core.storage import project_key

    return project_key(None, *ASSET_PREFIX, asset_id)


def designer_asset_dir() -> Path:
    """Local folder of uploaded/handoff assets (the S3 cache when STORAGE_BACKEND=s3)."""
    from platform_core.storage import get_storage, project_key

    path = get_storage().local_path(project_key(None, *ASSET_PREFIX))
    path.mkdir(parents=True, exist_ok=True)
    return path


def designer_asset_file(asset_id: str) -> Path:
    """Path of one asset; downloads it from S3 on a cache miss."""
    from platform_core.storage import get_storage

    return get_storage().local_path(_asset_key(asset_id))


def save_designer_asset(asset_id: str, data: bytes) -> None:
    """Store asset bytes in platform storage (S3 + cache, or local)."""
    from platform_core.storage import get_storage

    get_storage().put(_asset_key(asset_id), data)
