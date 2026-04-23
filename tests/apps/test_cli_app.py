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

    args = parser.parse_args(["desktop"])
    assert args.command == "desktop"
    assert args.api_url == "http://127.0.0.1:8765"

    args = parser.parse_args(["desktop-build"])
    assert args.command == "desktop-build"
    assert args.api_url == "http://127.0.0.1:8765"

    args = parser.parse_args(["desktop-open"])
    assert args.command == "desktop-open"
    assert args.api_url == "http://127.0.0.1:8765"

    args = parser.parse_args(["desktop-install"])
    assert args.command == "desktop-install"
    assert args.api_url == "http://127.0.0.1:8765"

    args = parser.parse_args(["desktop-stop"])
    assert args.command == "desktop-stop"

    args = parser.parse_args(["desktop-api", "--host", "0.0.0.0", "--port", "8877"])
    assert args.command == "desktop-api"
    assert args.host == "0.0.0.0"
    assert args.port == 8877

    args = parser.parse_args(["fullaccess", "login"])
    assert args.command == "fullaccess"
    assert args.fullaccess_command == "login"
    assert args.code is None

    args = parser.parse_args(["fullaccess", "login", "--code", "12345"])
    assert args.command == "fullaccess"
    assert args.fullaccess_command == "login"
    assert args.code == "12345"

    args = parser.parse_args(["runtime", "login"])
    assert args.command == "runtime"
    assert args.runtime_command == "login"

    args = parser.parse_args(["runtime", "code", "24680"])
    assert args.command == "runtime"
    assert args.runtime_command == "code"
    assert args.code == "24680"

    args = parser.parse_args(["runtime", "password"])
    assert args.command == "runtime"
    assert args.runtime_command == "password"
    assert args.password is None


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


def test_runtime_auth_commands_delegate_to_new_runtime_service(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)

    calls: list[tuple[str, str | None]] = []

    class FakeResult:
        def __init__(self, kind: str, message: str) -> None:
            self.kind = kind
            self.message = message

        def to_payload(self) -> dict[str, object]:
            return {
                "kind": self.kind,
                "message": self.message,
                "status": {
                    "state": "awaiting_code" if self.kind == "code_requested" else "authorized",
                    "authState": "authorizing" if self.kind == "code_requested" else "authorized",
                    "sessionState": "available",
                    "session": {"path": str(tmp_path / "runtime.session")},
                    "user": {"id": 42, "username": "astra_runtime", "phoneHint": "+***1122"},
                    "reasonCode": self.kind,
                    "reason": self.message,
                    "error": None,
                    "awaitingCode": self.kind == "code_requested",
                    "awaitingPassword": False,
                    "updatedAt": "2026-04-23T10:00:00+00:00",
                },
            }

    class FakeRuntimeService:
        async def request_code(self):
            calls.append(("request_code", None))
            return FakeResult("code_requested", "Код отправлен.")

        async def submit_code(self, code: str):
            calls.append(("submit_code", code))
            return FakeResult("authorized", "Код подтверждён.")

        async def submit_password(self, password: str):
            calls.append(("submit_password", password))
            return FakeResult("authorized", "Пароль подтверждён.")

        async def logout(self):
            calls.append(("logout", None))
            return FakeResult("logged_out", "Logout завершён.")

        async def reset(self):
            calls.append(("reset", None))
            return FakeResult("session_reset", "Состояние сброшено.")

    class FakeDatabase:
        async def dispose(self) -> None:
            calls.append(("dispose", None))

    async def fake_build_new_runtime_manager(_settings):
        return SimpleNamespace(
            new_runtime=FakeRuntimeService(),
            database=FakeDatabase(),
        )

    monkeypatch.setattr(app_module, "build_new_runtime_manager", fake_build_new_runtime_manager)
    monkeypatch.setattr(app_module.getpass, "getpass", lambda prompt: "secret-2fa")

    parser = app_module.build_parser()
    assert asyncio.run(app_module.run_cli(parser.parse_args(["runtime", "login"]))) == 0
    assert asyncio.run(app_module.run_cli(parser.parse_args(["runtime", "code", "24680"]))) == 0
    assert asyncio.run(app_module.run_cli(parser.parse_args(["runtime", "password"]))) == 0
    assert asyncio.run(app_module.run_cli(parser.parse_args(["runtime", "logout"]))) == 0
    assert asyncio.run(app_module.run_cli(parser.parse_args(["runtime", "reset"]))) == 0

    output = capsys.readouterr().out
    assert "Astra CLI / Runtime auth" in output
    assert "action: code_requested" in output
    assert "action: authorized" in output
    assert ("request_code", None) in calls
    assert ("submit_code", "24680") in calls
    assert ("submit_password", "secret-2fa") in calls
    assert ("logout", None) in calls
    assert ("reset", None) in calls


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


def test_desktop_api_command_runs_server_in_thread(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)

    from apps.desktop_api import app as desktop_app_module

    calls: list[tuple[str, int]] = []

    def fake_run_server(*, host: str, port: int) -> None:
        calls.append((host, port))

    monkeypatch.setattr(desktop_app_module, "run_server", fake_run_server)

    exit_code = asyncio.run(
        app_module.run_cli(
            app_module.build_parser().parse_args(
                ["desktop-api", "--host", "127.0.0.1", "--port", "8876"]
            )
        )
    )

    assert exit_code == 0
    assert calls == [("127.0.0.1", 8876)]


def test_desktop_command_prepares_launcher_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)
    monkeypatch.setattr(app_module, "get_repository_root", lambda: tmp_path)

    desktop_dir = tmp_path / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text('{"name":"astra-desktop"}', encoding="utf-8")

    launcher_calls: list[dict[str, str]] = []
    subprocess_calls: list[dict[str, object]] = []

    def fake_ensure_launcher_config(*, python_executable: str, api_url: str):
        launcher_calls.append(
            {
                "python_executable": python_executable,
                "api_url": api_url,
            }
        )
        return SimpleNamespace(), tmp_path / "launcher.json"

    def fake_subprocess_run(command, *, cwd, env, check):
        subprocess_calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": env,
                "check": check,
            }
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(app_module, "ensure_launcher_config", fake_ensure_launcher_config)
    monkeypatch.setattr(app_module.subprocess, "run", fake_subprocess_run)

    exit_code = asyncio.run(
        app_module.run_cli(
            app_module.build_parser().parse_args(["desktop", "--api-url", "http://127.0.0.1:8876"])
        )
    )

    assert exit_code == 0
    assert launcher_calls == [
        {
            "python_executable": app_module.sys.executable,
            "api_url": "http://127.0.0.1:8876",
        }
    ]
    assert subprocess_calls == [
        {
            "command": ["npm", "run", "desktop"],
            "cwd": str(desktop_dir),
            "env": subprocess_calls[0]["env"],
            "check": False,
        }
    ]
    assert subprocess_calls[0]["env"]["ASTRA_DESKTOP_API_URL"] == "http://127.0.0.1:8876"
    assert subprocess_calls[0]["env"]["VITE_ASTRA_DESKTOP_API_URL"] == "http://127.0.0.1:8876"
    assert subprocess_calls[0]["env"]["ASTRA_DESKTOP_API_PYTHON"] == app_module.sys.executable


def test_desktop_packaging_commands_delegate_to_helpers(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)

    calls: list[tuple[str, object]] = []

    def fake_build_desktop_app(*, python_executable: str, api_url: str):
        calls.append(("build", (python_executable, api_url)))
        return SimpleNamespace(
            detail="bundle built",
            app_path=tmp_path / "var" / "desktop" / "Astra Desktop.app",
            config_path=tmp_path / "launcher.json",
        )

    def fake_open_desktop_app(*, python_executable: str, api_url: str):
        calls.append(("open", (python_executable, api_url)))
        return SimpleNamespace(
            detail="desktop opened",
            app_path=tmp_path / "Applications" / "Astra Desktop.app",
            config_path=tmp_path / "launcher.json",
        )

    def fake_install_desktop_app(*, python_executable: str, api_url: str):
        calls.append(("install", (python_executable, api_url)))
        return SimpleNamespace(
            detail="desktop installed",
            app_path=tmp_path / "Applications" / "Astra Desktop.app",
            config_path=tmp_path / "launcher.json",
        )

    def fake_stop_desktop_app():
        calls.append(("stop", None))
        return SimpleNamespace(
            detail="desktop stopped",
            pid=4242,
        )

    monkeypatch.setattr(app_module, "build_desktop_app", fake_build_desktop_app)
    monkeypatch.setattr(app_module, "open_desktop_app", fake_open_desktop_app)
    monkeypatch.setattr(app_module, "install_desktop_app", fake_install_desktop_app)
    monkeypatch.setattr(app_module, "stop_desktop_app", fake_stop_desktop_app)

    build_code = asyncio.run(
        app_module.run_cli(
            app_module.build_parser().parse_args(["desktop-build", "--api-url", "http://127.0.0.1:8876"])
        )
    )
    open_code = asyncio.run(
        app_module.run_cli(
            app_module.build_parser().parse_args(["desktop-open", "--api-url", "http://127.0.0.1:8876"])
        )
    )
    install_code = asyncio.run(
        app_module.run_cli(
            app_module.build_parser().parse_args(["desktop-install", "--api-url", "http://127.0.0.1:8876"])
        )
    )
    stop_code = asyncio.run(app_module.run_cli(app_module.build_parser().parse_args(["desktop-stop"])))

    output = capsys.readouterr().out

    assert build_code == 0
    assert open_code == 0
    assert install_code == 0
    assert stop_code == 0
    assert calls == [
        ("build", (app_module.sys.executable, "http://127.0.0.1:8876")),
        ("open", (app_module.sys.executable, "http://127.0.0.1:8876")),
        ("install", (app_module.sys.executable, "http://127.0.0.1:8876")),
        ("stop", None),
    ]
    assert "bundle built" in output
    assert "desktop opened" in output
    assert "desktop installed" in output
    assert "desktop stopped" in output
    assert "bridge pid: 4242" in output


def test_main_runs_desktop_api_without_asyncio(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "chdir_to_repository_root", lambda: tmp_path)
    monkeypatch.setattr(
        app_module,
        "_parse_args",
        lambda: SimpleNamespace(command="desktop-api", host="127.0.0.1", port=8876),
    )

    from apps.desktop_api import app as desktop_app_module

    calls: list[tuple[str, int]] = []

    def fake_run_server(*, host: str, port: int) -> None:
        calls.append((host, port))

    monkeypatch.setattr(desktop_app_module, "run_server", fake_run_server)
    monkeypatch.setattr(
        app_module.asyncio,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("asyncio.run must not be used")),
    )

    exit_code = app_module.main()

    assert exit_code == 0
    assert calls == [("127.0.0.1", 8876)]
