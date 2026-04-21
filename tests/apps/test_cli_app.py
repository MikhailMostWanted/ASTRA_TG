import asyncio
from pathlib import Path
from types import SimpleNamespace

from apps.cli import app as app_module
from apps.cli.processes import ProcessState
from apps.cli.runtime import DatabaseCheckResult, DoctorSnapshot, ProviderCheckResult


def test_cli_parser_supports_expected_commands() -> None:
    parser = app_module.build_parser()

    args = parser.parse_args(["start", "bot"])
    assert args.command == "start"
    assert args.component == "bot"

    args = parser.parse_args(["status"])
    assert args.command == "status"
    assert args.component is None

    args = parser.parse_args(["logs", "worker", "--tail", "25"])
    assert args.command == "logs"
    assert args.component == "worker"
    assert args.tail == 25

    args = parser.parse_args(["export", "--stdout"])
    assert args.command == "export"
    assert args.stdout is True


def test_status_command_handles_missing_processes(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)
    monkeypatch.setattr(app_module, "get_repository_root", lambda: tmp_path)
    monkeypatch.setattr(app_module, "get_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(app_module, "pathlib_from_sys_executable", lambda: tmp_path / ".venv/bin/python")
    monkeypatch.setattr(
        app_module,
        "inspect_process",
        lambda component: ProcessState(
            component=component,
            pid_path=tmp_path / "var/run" / f"astra-{component}.pid",
            log_path=tmp_path / "var/log" / f"astra-{component}.log",
            pid=None,
            running=False,
            managed=False,
            stale_pid_file=False,
            command=None,
            detail="PID-файл отсутствует.",
        ),
    )

    async def fake_check_database(_settings):
        return DatabaseCheckResult(
            database_url="sqlite+aiosqlite:///tmp/astra.db",
            sqlite_path=tmp_path / "var/astra.db",
            available=False,
            detail="SQLite база ещё не создана.",
        )

    async def fake_check_provider(_settings):
        return ProviderCheckResult(
            enabled=True,
            configured=True,
            available=False,
            provider_name="ollama",
            reason="Провайдер недоступен.",
        )

    monkeypatch.setattr(app_module, "check_database", fake_check_database)
    monkeypatch.setattr(app_module, "check_provider", fake_check_provider)

    exit_code = asyncio.run(app_module.run_cli(app_module.build_parser().parse_args(["status"])))
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Astra CLI / Status" in output
    assert "Bot: [OFF] не запущен" in output
    assert "Worker: [OFF] не запущен" in output
    assert "provider: [WARN] ollama" in output


def test_backup_and_export_delegate_to_ops(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)

    calls: list[tuple[str, bool]] = []

    async def fake_run_ops(command: str, *, stdout: bool = False) -> int:
        calls.append((command, stdout))
        return 0

    monkeypatch.setattr(app_module, "run_ops_command", fake_run_ops)

    backup_code = asyncio.run(app_module.run_cli(app_module.build_parser().parse_args(["backup"])))
    export_code = asyncio.run(
        app_module.run_cli(app_module.build_parser().parse_args(["export", "--stdout"]))
    )

    assert backup_code == 0
    assert export_code == 0
    assert calls == [("backup", False), ("export", True)]


def test_doctor_command_handles_snapshot(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)

    async def fake_build_doctor_snapshot(_settings):
        return DoctorSnapshot(
            readiness=SimpleNamespace(next_command="/checklist"),
            doctor=SimpleNamespace(
                ok_items=("База данных отвечает.",),
                warnings=("Критичных проблем не найдено.",),
                next_steps=("Можно запускать bot.",),
            ),
            error=None,
        )

    monkeypatch.setattr(app_module, "build_doctor_snapshot", fake_build_doctor_snapshot)

    exit_code = asyncio.run(app_module.run_cli(app_module.build_parser().parse_args(["doctor"])))
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Astra CLI / Doctor" in output
    assert "База данных отвечает." in output
    assert "Следующая рекомендуемая команда: /checklist" in output
