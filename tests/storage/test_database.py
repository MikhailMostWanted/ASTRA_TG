import asyncio
from pathlib import Path

from sqlalchemy import text

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime


def test_database_bootstrap_initializes_sqlite_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "nested" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        settings = Settings()
        runtime = build_database_runtime(settings)

        await bootstrap_database(runtime)

        assert database_path.parent.exists()

        async with runtime.engine.begin() as connection:
            result = await connection.execute(text("SELECT 1"))

        assert result.scalar_one() == 1
        await runtime.dispose()

    asyncio.run(run_assertions())
