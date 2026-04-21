import asyncio
from pathlib import Path

from config.settings import Settings
from services.startup_validation import StartupValidationService
from storage.database import bootstrap_database, build_database_runtime


def test_bot_startup_validation_reports_missing_token_and_disabled_optional_layers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "startup-bot" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("LLM_ENABLED", "false")
        monkeypatch.setenv("FULLACCESS_ENABLED", "false")

        settings = Settings()
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)

        report = await StartupValidationService(
            settings=settings,
            session_factory=runtime.session_factory,
        ).build_bot_report()

        assert report.can_start is False
        assert not _find_check(report, "telegram_bot_token").ready
        assert _find_check(report, "telegram_bot_token").critical is True
        assert _find_check(report, "database").ready is True
        assert _find_check(report, "schema_revision").ready is True
        assert _find_check(report, "provider_layer").ready is True
        assert "выключен" in _find_check(report, "provider_layer").detail.lower()
        assert _find_check(report, "fullaccess_layer").ready is True
        assert "выключен" in _find_check(report, "fullaccess_layer").detail.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_worker_startup_validation_accepts_disabled_optional_layers(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "startup-worker" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("LLM_ENABLED", "false")
        monkeypatch.setenv("FULLACCESS_ENABLED", "false")

        settings = Settings()
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)

        report = await StartupValidationService(
            settings=settings,
            session_factory=runtime.session_factory,
        ).build_worker_report()

        assert report.can_start is True
        assert _find_check(report, "database").ready is True
        assert _find_check(report, "schema_revision").ready is True
        assert _find_check(report, "worker_jobs").ready is True
        assert _find_check(report, "provider_layer").ready is True
        assert _find_check(report, "fullaccess_layer").ready is True
        assert any("owner chat" in item.lower() for item in report.warnings)

        await runtime.dispose()

    asyncio.run(run_assertions())


def _find_check(report, key: str):
    for item in report.checks:
        if item.key == key:
            return item
    raise KeyError(key)
