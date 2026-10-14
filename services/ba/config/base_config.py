"""Centralized application configuration management using Pydantic BaseSettings."""

import urllib.parse
from typing import List  # noqa: UP035

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded automatically from environment variables (.env)."""

    model_config = SettingsConfigDict(
        # No env_file: the single platform/.env is injected by Compose (env_file)
        # or exported by the Makefile for local runs.
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ── Application ───────────────────────────────────────────
    app_name: str = Field(
        default="Unify AI Product",
        description="Application name",
    )

    # ── Database Configuration ────────────────────────────────
    db_host: str = Field(
        validation_alias=AliasChoices("POSTGRES_HOST", "DB_HOST"),default="localhost", description="PostgreSQL host")
    db_port: int = Field(
        validation_alias=AliasChoices("POSTGRES_PORT", "DB_PORT"),default=5432, description="PostgreSQL port")
    db_name: str = Field(
        validation_alias=AliasChoices("POSTGRES_DB", "DB_NAME"),default="unify", description="PostgreSQL database name")
    db_user: str = Field(
        validation_alias=AliasChoices("POSTGRES_USER", "DB_USER"),default="postgres", description="PostgreSQL user")
    db_password: str = Field(
        validation_alias=AliasChoices("POSTGRES_PASSWORD", "DB_PASSWORD"),default="admin123", description="PostgreSQL password")
    db_min_pool_size: int = Field(
        validation_alias=AliasChoices("POSTGRES_POOL_MIN", "DB_MIN_POOL_SIZE"),default=2, description="Minimum connection pool size")
    db_max_pool_size: int = Field(
        validation_alias=AliasChoices("POSTGRES_POOL_MAX", "DB_MAX_POOL_SIZE"),
        default=15, description="Maximum connection pool size"
    )
    db_connect_timeout: float = Field(
        default=10.0, description="Connection timeout in seconds"
    )
    db_connect_retries: int = Field(default=3, description="Connection retry attempts")
    db_schema: str = Field(
        default="ba",
        validation_alias=AliasChoices("BA_DB_SCHEMA", "DB_SCHEMA"),
        description="Postgres schema owned by the BA service (search_path)",
    )

    # ── Language Model Configuration ──────────────────────────
    # BA API talks to one LiteLLM Proxy; provider routing lives in its YAML.
    litellm_api_base_url: str = Field(
        default="http://litellm:4000/v1",
        description="Internal LiteLLM Proxy OpenAI-compatible URL",
    )
    litellm_model_name: str = Field(
        default="ba-company",
        description="LiteLLM model group requested by the BA Agent",
    )
    litellm_master_key: str = Field(
        default="sk-ba-local-dev",
        description="Internal key used by BA API to authenticate to LiteLLM Proxy",
    )
    use_litellm_proxy: bool = Field(
        validation_alias=AliasChoices("BA_USE_LITELLM_PROXY", "USE_LITELLM_PROXY"),
        default=False,
        description="If true, BA talks to the optional compose LiteLLM service",
    )
    llm_gate_api_base_url: str = Field(
        validation_alias=AliasChoices("LLM_BASE_URL", "LLM_GATE_API_BASE_URL"),
        default="https://llm-gate.imespro.ai/v1",
        description="Company OpenAI-compatible gate used when LiteLLM is not running",
    )
    llm_gate_api_key: str = Field(
        validation_alias=AliasChoices("LLM_API_KEY", "LLM_GATE_API_KEY"),
        default="",
        description="API key for the company LLM gate",
    )
    llm_gate_model_name: str = Field(
        validation_alias=AliasChoices("BA_LLM_MODEL", "LLM_GATE_MODEL_NAME"),
        default="Qwen3.5-27B-AWQ",
        description="Model id on the company LLM gate",
    )
    top_p: float = Field(default=0.1, description="Top-p sampling parameter")
    temperature: float = Field(default=0.0, description="Temperature parameter")
    presence_penalty: float = Field(default=0.0, description="Presence penalty")
    frequency_penalty: float = Field(default=0.0, description="Frequency penalty")
    max_tokens: int = Field(default=8192, description="Maximum tokens for responses")

    # ── Logging & Server Configuration ────────────────────────
    log_level: str = Field(
        validation_alias=AliasChoices("PLATFORM_LOG_LEVEL", "LOG_LEVEL"),default="INFO", description="Logging level")
    log_format: str = Field(
        default="text",
        description="Log output format ('text' or 'json')",
    )
    origins: str = Field(
        validation_alias=AliasChoices("PLATFORM_CORS_ORIGINS", "ORIGINS"),
        default="*",
        description="Comma-separated allowed CORS origins",
    )
    swagger_enabled: bool = Field(
        validation_alias=AliasChoices("PLATFORM_SWAGGER_ENABLED", "SWAGGER_ENABLED"),
        default=True,
        description="Enable Swagger API documentation",
    )

    # ── Designer handoff ─────────────────────────────────────
    designer_enabled: bool = Field(
        default=False,
        description="Enable the explicit BA -> Designer handoff action",
    )
    designer_base_url: str = Field(
        validation_alias=AliasChoices("DESIGNER_INTERNAL_URL", "DESIGNER_BASE_URL"),
        default="http://designer-backend:8282",
        description="Designer Agent API base URL",
    )
    designer_ui_base_url: str = Field(
        default="",
        description="Browser URL used to open the Designer session "
        "(defaults to PLATFORM_PUBLIC_URL + /designer)",
    )
    platform_public_url: str = Field(
        default="http://localhost:8080",
        description="Gateway origin the browser uses for every platform UI",
    )
    openpencil_ui_base_url: str = Field(
        validation_alias=AliasChoices("OPENPENCIL_DEFAULT_EDITOR_URL", "OPENPENCIL_UI_BASE_URL"),
        default="http://127.0.0.1:1420",
        description="Browser URL used to open the OpenPencil canvas",
    )
    designer_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    designer_shared_secret: str = Field(default="")

    # ── ADK Artifact Configuration ────────────────────────────
    artifact_root_dir: str = Field(
        validation_alias=AliasChoices("BA_ARTIFACT_ROOT_DIR", "ARTIFACT_ROOT_DIR"),
        default="/tmp/unify-agent-artifacts",
        description="Root directory for ADK FileArtifactService file storage",
    )

    # ── Wiki Knowledge MVP (approved documents) ───────────────
    wiki_mvp_root: str = Field(
        default="",
        description="Path to Wiki Knowledge MVP checkout (config/ + data/wiki.db)",
    )
    wiki_data_dir: str = Field(
        default="",
        description="Optional wiki store root override (must contain config/manifest.json)",
    )
    wiki_default_project_id: str = Field(
        default="",
        description=(
            "Optional override only; new features use project_id_for_session(session_id). "
            "Do not treat as a shared MES default."
        ),
    )

    # ── History Filter Configuration ──────────────────────────
    slice_history: int = Field(
        validation_alias=AliasChoices("BA_SLICE_HISTORY", "SLICE_HISTORY"),
        default=8,
        description="Maximum number of conversation turns to keep in LLM context window",
    )

    # ── Properties & Helpers ──────────────────────────────────
    @model_validator(mode="after")
    def _default_designer_ui_url(self) -> "Settings":
        if not self.designer_ui_base_url:
            self.designer_ui_base_url = self.platform_public_url.rstrip("/") + "/designer"
        return self

    @property
    def database_url(self) -> str:
        """Get fully-qualified asyncpg PostgreSQL connection URL with URL-encoded password.

        asyncpg ignores libpq ``options``; pair with ``async_engine_kwargs``.
        """
        encoded_password = urllib.parse.quote_plus(self.db_password)
        return (
            f"postgresql+asyncpg://{self.db_user}:{encoded_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def async_engine_kwargs(self) -> dict:
        """Pin asyncpg connections (ADK sessions) to the BA schema.

        Tests swap ``database_url`` for SQLite, which has no search_path.
        """
        if not self.database_url.startswith("postgresql"):
            return {}
        return {"connect_args": {"server_settings": {"search_path": self.db_schema}}}

    @property
    def origins_list(self) -> List[str]:
        """Convert comma-separated origins string to a list of domains."""
        return [origin.strip() for origin in self.origins.split(",") if origin.strip()]


# Global settings singleton
settings = Settings()
