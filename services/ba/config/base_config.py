"""Centralized application configuration management using Pydantic BaseSettings."""

import urllib.parse
from typing import List  # noqa: UP035

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded automatically from environment variables (.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────
    app_name: str = Field(
        default="Unify AI Product",
        description="Application name",
    )

    # ── Database Configuration ────────────────────────────────
    db_host: str = Field(default="localhost", description="PostgreSQL host")
    db_port: int = Field(default=5432, description="PostgreSQL port")
    db_name: str = Field(default="unify", description="PostgreSQL database name")
    db_user: str = Field(default="postgres", description="PostgreSQL user")
    db_password: str = Field(default="admin123", description="PostgreSQL password")
    db_min_pool_size: int = Field(default=2, description="Minimum connection pool size")
    db_max_pool_size: int = Field(
        default=15, description="Maximum connection pool size"
    )
    db_connect_timeout: float = Field(
        default=10.0, description="Connection timeout in seconds"
    )
    db_connect_retries: int = Field(default=3, description="Connection retry attempts")

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
        default=False,
        description="If true, BA talks to the optional compose LiteLLM service",
    )
    llm_gate_api_base_url: str = Field(
        default="https://llm-gate.imespro.ai/v1",
        description="Company OpenAI-compatible gate used when LiteLLM is not running",
    )
    llm_gate_api_key: str = Field(
        default="",
        description="API key for the company LLM gate",
    )
    llm_gate_model_name: str = Field(
        default="Qwen3.5-27B-AWQ",
        description="Model id on the company LLM gate",
    )
    top_p: float = Field(default=0.1, description="Top-p sampling parameter")
    temperature: float = Field(default=0.0, description="Temperature parameter")
    presence_penalty: float = Field(default=0.0, description="Presence penalty")
    frequency_penalty: float = Field(default=0.0, description="Frequency penalty")
    max_tokens: int = Field(default=8192, description="Maximum tokens for responses")

    # ── Logging & Server Configuration ────────────────────────
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="text",
        description="Log output format ('text' or 'json')",
    )
    origins: str = Field(
        default="*",
        description="Comma-separated allowed CORS origins",
    )
    swagger_enabled: bool = Field(
        default=True,
        description="Enable Swagger API documentation",
    )

    # ── Designer handoff ─────────────────────────────────────
    designer_enabled: bool = Field(
        default=False,
        description="Enable the explicit BA -> Designer handoff action",
    )
    designer_base_url: str = Field(
        default="http://designer-backend:8282",
        description="Designer Agent API base URL",
    )
    designer_ui_base_url: str = Field(
        default="http://127.0.0.1:3232",
        description="Browser URL used to open the Designer session",
    )
    openpencil_ui_base_url: str = Field(
        default="http://127.0.0.1:1420",
        description="Browser URL used to open the OpenPencil canvas",
    )
    designer_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    designer_shared_secret: str = Field(default="")

    # ── ADK Artifact Configuration ────────────────────────────
    artifact_root_dir: str = Field(
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
        default=8,
        description="Maximum number of conversation turns to keep in LLM context window",
    )

    # ── Properties & Helpers ──────────────────────────────────
    @property
    def database_url(self) -> str:
        """Get fully-qualified asyncpg PostgreSQL connection URL with URL-encoded password."""
        encoded_password = urllib.parse.quote_plus(self.db_password)
        return (
            f"postgresql+asyncpg://{self.db_user}:{encoded_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def origins_list(self) -> List[str]:
        """Convert comma-separated origins string to a list of domains."""
        return [origin.strip() for origin in self.origins.split(",") if origin.strip()]


# Global settings singleton
settings = Settings()
