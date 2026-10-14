import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Platform layout flattens Designer/backend into services/designer, so the
# service root (docs/, data/, logs/) is two levels above this file.
PROJECT_DIR = Path(__file__).resolve().parents[2]


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

    openpencil_mcp_auth_token: str = ""
    # Default OpenPencil instance; per-designer instances live in the
    # designer.openpencil_instances table (refactor-plan/06).
    openpencil_default_mcp_url: str = "http://host.docker.internal:7600/mcp"
    openpencil_default_editor_url: str = "http://localhost:1420"
    platform_env: str = "dev"
    designer_shared_secret: str = ""
    mcp_timeout_seconds: int = 150
    # The workspace root owns the read-only design-systems folder. Runtime
    # caches may still live alongside it under ``designer-data``.
    design_data_dir: Path = PROJECT_DIR.parent
    openpencil_cli: str = "openpencil"
    unsplash_access_key: str = ""

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


def designer_asset_dir() -> Path:
    """Uploaded/handoff asset bytes, inside the shared platform storage.

    Key ``shared/designer/assets`` follows the S3 layout; assets move under
    ``projects/<id>/`` once sessions carry a project (Sprint 3).
    """
    from platform_core.storage import get_storage, project_key

    path = get_storage().local_path(project_key(None, "designer", "assets"))
    assert path is not None
    path.mkdir(parents=True, exist_ok=True)
    return path
