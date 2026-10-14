import hashlib
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parents[3]
# Load local defaults without overriding environment variables supplied by
# Docker Compose. This lets the same .env work for local development while
# container-specific paths such as /app/designer-data remain effective.
load_dotenv(PROJECT_DIR / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    backend_port: int
    database_url: str
    cors_origins: str

    llm_model: str
    designer_model: str = ""
    api_key: str
    base_url: str

    openpencil_mcp_auth_token: str = ""
    mcp_timeout_seconds: int
    # The workspace root owns the read-only design-systems folder. Runtime
    # caches may still live alongside it under ``designer-data``.
    design_data_dir: Path = PROJECT_DIR.parent
    openpencil_cli: str = "openpencil"
    unsplash_access_key: str = ""

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
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        raw = self.database_url.removeprefix(prefix)
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
