import asyncio
from pathlib import Path

from apps.worker.app import run_worker_once
from config.settings import Settings


def test_worker_run_once_bootstraps_database(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "worker" / "astra.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

    settings = Settings()

    asyncio.run(run_worker_once(settings))

    assert database_path.parent.exists()
