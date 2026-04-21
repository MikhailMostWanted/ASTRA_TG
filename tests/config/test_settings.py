from pathlib import Path

from config.settings import Settings


def test_settings_read_bot_token_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

    settings = Settings()

    assert settings.telegram_bot_token == "123456:TEST_TOKEN"


def test_settings_expose_sqlite_database_path(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "astra.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

    settings = Settings()

    assert settings.sqlite_database_path == database_path


def test_settings_keep_llm_disabled_and_optional_by_default(monkeypatch) -> None:
    for key in (
        "LLM_ENABLED",
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_FAST",
        "LLM_MODEL_DEEP",
        "LLM_TIMEOUT",
        "LLM_REFINE_REPLY_ENABLED",
        "LLM_REFINE_DIGEST_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings()

    assert settings.llm_enabled is False
    assert settings.llm_provider is None
    assert settings.llm_base_url is None
    assert settings.llm_api_key is None
    assert settings.llm_model_fast is None
    assert settings.llm_model_deep is None
    assert settings.llm_timeout == 15.0
    assert settings.llm_refine_reply_enabled is False
    assert settings.llm_refine_digest_enabled is False
