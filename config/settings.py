from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./var/astra.db"


class Settings(BaseSettings):
    """Shared environment-driven settings for all local apps."""

    telegram_bot_token: str | None = None
    database_url: str = DEFAULT_DATABASE_URL
    log_level: str = "INFO"
    llm_enabled: bool = False
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_fast: str | None = None
    llm_model_deep: str | None = None
    llm_timeout: float = 15.0
    llm_refine_reply_enabled: bool = False
    llm_refine_digest_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlite_database_path(self) -> Path | None:
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None

        return Path(self.database_url.removeprefix(prefix)).expanduser()
