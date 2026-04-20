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
