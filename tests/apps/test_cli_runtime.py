import asyncio
from pathlib import Path

from apps.cli import runtime as runtime_module
from apps.cli.processes import inspect_process, stop_component


def test_component_runtime_paths_are_stable() -> None:
    bot = runtime_module.get_component_files("bot")
    worker = runtime_module.get_component_files("worker")

    assert bot.pid_path == runtime_module.RUN_DIR / "astra-bot.pid"
    assert bot.log_path == runtime_module.LOG_DIR / "astra-bot.log"
    assert worker.pid_path == runtime_module.RUN_DIR / "astra-worker.pid"
    assert worker.log_path == runtime_module.LOG_DIR / "astra-worker.log"


def test_inspect_process_reports_absent_pid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime_module, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(runtime_module, "LOG_DIR", tmp_path / "log")

    state = inspect_process("bot")

    assert state.running is False
    assert state.pid is None
    assert "PID-файл отсутствует" in state.detail


def test_stop_component_without_pid_is_safe(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime_module, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(runtime_module, "LOG_DIR", tmp_path / "log")

    result = stop_component("worker")

    assert result.ok is True
    assert result.stopped is False
    assert "Не запущен" in result.detail


def test_check_database_reports_missing_sqlite_file(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "var" / "astra.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

    result = asyncio.run(runtime_module.check_database(runtime_module.Settings()))

    assert result.available is False
    assert str(database_path) in result.detail
