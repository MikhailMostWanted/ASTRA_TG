from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys

from apps.bot.app import run_bot
from apps.cli.formatting import format_action_results, format_doctor, format_logs, format_status
from apps.cli.processes import inspect_process, start_component, stop_component
from apps.cli.runtime import (
    COMPONENTS,
    DEFAULT_WORKER_INTERVAL_SECONDS,
    build_doctor_snapshot,
    check_database,
    check_provider,
    chdir_to_repository_root,
    get_env_path,
    get_repository_root,
    run_ops_command,
    tail_log,
)
from apps.worker.app import run_worker_once
from config.settings import Settings
from core.logging import configure_logging, get_logger, log_event, log_exception
from fullaccess.cli import run_fullaccess_command


LOGGER = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Локальный process manager и operational CLI для Astra AFT.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_component_command(
        subparsers,
        "start",
        help_text="Поднять bot и worker в фоне.",
    )
    _add_component_command(
        subparsers,
        "stop",
        help_text="Остановить процессы, запущенные через astratg.",
    )
    _add_component_command(
        subparsers,
        "restart",
        help_text="Перезапустить bot и worker.",
    )
    _add_component_command(
        subparsers,
        "status",
        help_text="Показать состояние процессов и operational checks.",
    )

    subparsers.add_parser(
        "doctor",
        help="Построить diagnostic doctor-отчёт поверх существующего operational слоя.",
    )

    logs_parser = subparsers.add_parser(
        "logs",
        help="Показать пути к логам и при необходимости последние строки.",
    )
    logs_parser.add_argument("component", nargs="?", choices=COMPONENTS)
    logs_parser.add_argument(
        "--tail",
        type=int,
        default=0,
        help="Показать последние N строк из лог-файлов.",
    )

    subparsers.add_parser(
        "backup",
        help="Сделать backup через существующий ops-слой.",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Сделать operational export через существующий ops-слой.",
    )
    export_parser.add_argument(
        "--stdout",
        action="store_true",
        help="Дополнительно вывести JSON в stdout.",
    )

    desktop_parser = subparsers.add_parser(
        "desktop",
        help="Запустить Tauri desktop в dev-режиме поверх локального desktop API.",
    )
    desktop_parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8765",
        help="URL локального desktop API, который увидит frontend.",
    )

    desktop_api_parser = subparsers.add_parser(
        "desktop-api",
        help="Поднять локальный desktop bridge/API.",
    )
    desktop_api_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host для desktop API.",
    )
    desktop_api_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port для desktop API.",
    )

    fullaccess_parser = subparsers.add_parser(
        "fullaccess",
        help="Безопасные локальные команды для experimental full-access.",
    )
    fullaccess_subparsers = fullaccess_parser.add_subparsers(
        dest="fullaccess_command",
        required=True,
    )
    fullaccess_subparsers.add_parser(
        "status",
        help="Показать состояние full-access слоя.",
    )
    login_parser = fullaccess_subparsers.add_parser(
        "login",
        help="Безопасно запросить код и завершить локальный вход через CLI.",
    )
    login_parser.add_argument(
        "--code",
        help="Код Telegram. Если не указан, CLI спросит его интерактивно.",
    )
    fullaccess_subparsers.add_parser(
        "logout",
        help="Локально удалить session и pending auth.",
    )
    return parser


async def run_cli(args: argparse.Namespace) -> int:
    chdir_to_repository_root()

    if args.command == "start":
        return await _handle_start(args.component)
    if args.command == "stop":
        return await _handle_stop(args.component)
    if args.command == "restart":
        return await _handle_restart(args.component)
    if args.command == "status":
        return await _handle_status(args.component)
    if args.command == "doctor":
        return await _handle_doctor()
    if args.command == "logs":
        return await _handle_logs(args.component, tail_lines=args.tail)
    if args.command == "backup":
        return await run_ops_command("backup")
    if args.command == "export":
        return await run_ops_command("export", stdout=args.stdout)
    if args.command == "desktop-api":
        return await _handle_desktop_api(host=args.host, port=args.port)
    if args.command == "desktop":
        return await _handle_desktop(api_url=args.api_url)
    if args.command == "fullaccess":
        return await run_fullaccess_command(
            args.fullaccess_command,
            code=getattr(args, "code", None),
        )
    if args.command == "_run-bot":
        await _run_managed_bot()
        return 0
    if args.command == "_run-worker":
        await _run_managed_worker()
        return 0

    raise ValueError(f"Неизвестная команда: {args.command}")


def main() -> int:
    args = _parse_args()
    if args.command == "desktop-api":
        chdir_to_repository_root()
        from apps.desktop_api.app import run_server

        run_server(host=args.host, port=args.port)
        return 0
    return asyncio.run(run_cli(args))


async def _handle_start(component: str | None) -> int:
    targets = _resolve_targets(component)
    results = [start_component(target, python_executable=sys.executable) for target in targets]
    print(format_action_results("start", results))
    return 0 if all(result.ok for result in results) else 1


async def _handle_stop(component: str | None) -> int:
    targets = _resolve_targets(component, reverse=True)
    results = [stop_component(target) for target in targets]
    print(format_action_results("stop", results))
    return 0 if all(result.ok for result in results) else 1


async def _handle_restart(component: str | None) -> int:
    stop_targets = _resolve_targets(component, reverse=True)
    start_targets = _resolve_targets(component)

    stop_results = [stop_component(target) for target in stop_targets]
    start_results = [start_component(target, python_executable=sys.executable) for target in start_targets]

    print(format_action_results("stop", stop_results))
    print()
    print(format_action_results("start", start_results))
    return 0 if all(result.ok for result in [*stop_results, *start_results]) else 1


async def _handle_status(component: str | None) -> int:
    targets = _resolve_targets(component)
    states = [inspect_process(target) for target in targets]

    database = None
    provider = None
    if component is None:
        settings = Settings()
        database = await check_database(settings)
        provider = await check_provider(settings)

    print(
        format_status(
            repository_root=get_repository_root(),
            env_path=get_env_path(),
            env_exists=get_env_path().exists(),
            python_executable=pathlib_from_sys_executable(),
            component_states=states,
            database=database,
            provider=provider,
        )
    )
    return 0


async def _handle_doctor() -> int:
    snapshot = await build_doctor_snapshot(Settings())
    print(format_doctor(snapshot))
    return 0 if snapshot.error is None else 1


async def _handle_logs(component: str | None, *, tail_lines: int) -> int:
    targets = _resolve_targets(component)
    states = [inspect_process(target) for target in targets]
    tail_lookup = {
        state.component: tail_log(state.log_path, lines=tail_lines)
        for state in states
    }
    print(
        format_logs(
            component_states=states,
            tail_lines=tail_lines,
            tail_lookup=tail_lookup,
        )
    )
    return 0


async def _handle_desktop_api(*, host: str, port: int) -> int:
    from apps.desktop_api.app import run_server

    await asyncio.to_thread(run_server, host=host, port=port)
    return 0


async def _handle_desktop(*, api_url: str) -> int:
    desktop_dir = get_repository_root() / "apps" / "desktop"
    package_json = desktop_dir / "package.json"
    if not package_json.exists():
        raise ValueError(
            f"Desktop app ещё не найден: {package_json}. Сначала добавь apps/desktop."
        )

    env = os.environ.copy()
    env["ASTRA_DESKTOP_API_URL"] = api_url
    env["VITE_ASTRA_DESKTOP_API_URL"] = api_url
    env["ASTRA_DESKTOP_API_PYTHON"] = sys.executable
    result = subprocess.run(
        ["npm", "run", "desktop"],
        cwd=str(desktop_dir),
        env=env,
        check=False,
    )
    return int(result.returncode)


async def _run_managed_bot() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log_event(
        LOGGER,
        20,
        "cli.bot_runtime.started",
        "astratg bot runtime запущен.",
        repository_root=get_repository_root(),
        python_executable=sys.executable,
    )
    await _run_with_signals(run_bot(settings))


async def _run_managed_worker() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log_event(
        LOGGER,
        20,
        "cli.worker_runtime.started",
        "astratg worker runtime запущен.",
        repository_root=get_repository_root(),
        python_executable=sys.executable,
        interval_seconds=DEFAULT_WORKER_INTERVAL_SECONDS,
    )
    await _run_with_signals(_worker_loop(settings))


async def _worker_loop(settings: Settings) -> None:
    while True:
        try:
            await run_worker_once(settings)
        except asyncio.CancelledError:
            log_event(
                LOGGER,
                20,
                "cli.worker_runtime.cancelled",
                "astratg worker runtime получил сигнал остановки.",
            )
            raise
        except Exception as error:
            log_exception(
                LOGGER,
                "cli.worker_runtime.iteration_failed",
                error,
                message="Итерация astratg worker завершилась ошибкой.",
            )

        await asyncio.sleep(DEFAULT_WORKER_INTERVAL_SECONDS)


async def _run_with_signals(coroutine) -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(coroutine)

    def _cancel_running_task() -> None:
        if not task.done():
            task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _cancel_running_task)
        except NotImplementedError:  # pragma: no cover - защитный код для несовместимых event loop
            pass

    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.remove_signal_handler(sig)
            except NotImplementedError:  # pragma: no cover - защитный код для несовместимых event loop
                pass


def _add_component_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    *,
    help_text: str,
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("component", nargs="?", choices=COMPONENTS)


def _resolve_targets(component: str | None, *, reverse: bool = False) -> list[str]:
    items = list(COMPONENTS if component is None else (component,))
    if reverse:
        items.reverse()
    return items


def pathlib_from_sys_executable():
    from pathlib import Path

    return Path(sys.executable)


def _parse_args() -> argparse.Namespace:
    if len(sys.argv) > 1 and sys.argv[1] in {"_run-bot", "_run-worker"}:
        return argparse.Namespace(command=sys.argv[1])
    return build_parser().parse_args()
