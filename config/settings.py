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
    fullaccess_enabled: bool = False
    fullaccess_api_id: int | None = None
    fullaccess_api_hash: str | None = None
    fullaccess_session_path: str = "./var/fullaccess.session"
    fullaccess_session_string: str | None = None
    fullaccess_phone: str | None = None
    fullaccess_readonly: bool = True
    fullaccess_sync_limit: int = 200
    runtime_chat_roster_backend: str = "legacy"
    runtime_message_workspace_backend: str = "legacy"
    runtime_reply_generation_backend: str = "legacy"
    runtime_send_path_backend: str = "legacy"
    runtime_autopilot_control_backend: str = "legacy"
    runtime_new_enabled: bool = False
    runtime_new_session_path: str = "./var/new_telegram_runtime.session"
    runtime_new_device_name: str = "Astra Desktop new runtime"
    runtime_new_product_surfaces_enabled: bool = False

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

    @property
    def fullaccess_session_file(self) -> Path:
        path = Path(self.fullaccess_session_path).expanduser()
        if path.suffix != ".session":
            path = path.with_suffix(f"{path.suffix}.session" if path.suffix else ".session")
        return path
