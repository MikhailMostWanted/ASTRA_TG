from __future__ import annotations

import argparse
import asyncio
import json

from config.settings import Settings
from core.logging import configure_logging
from services.operational_tools import OperationalBackupService, OperationalExportService
from storage.database import bootstrap_database, build_database_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operational utilities для Astra AFT.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("backup", help="Сделать timestamped backup локальной SQLite-базы.")

    export_parser = subparsers.add_parser(
        "export",
        help="Сохранить operational summary в JSON-файл.",
    )
    export_parser.add_argument(
        "--stdout",
        action="store_true",
        help="Дополнительно вывести JSON в stdout.",
    )

    subparsers.add_parser(
        "status",
        help="Показать путь к базе и доступность backup/export утилит.",
    )
    return parser


async def run_ops(args: argparse.Namespace) -> int:
    settings = Settings()
    configure_logging(settings.log_level)

    runtime = build_database_runtime(settings)
    try:
        if args.command == "backup":
            result = await OperationalBackupService(
                settings=settings,
                session_factory=runtime.session_factory,
            ).create_backup()
            print(f"Backup создан: {result.path}")
            print(f"Источник: {result.source_path}")
            return 0

        if args.command == "export":
            await bootstrap_database(runtime)
            result = await OperationalExportService(
                settings=settings,
                session_factory=runtime.session_factory,
            ).export_summary()
            print(f"Export создан: {result.path}")
            if args.stdout:
                print(json.dumps(result.payload, ensure_ascii=False, indent=2))
            return 0

        if args.command == "status":
            print(f"database_url: {settings.database_url}")
            print(
                "sqlite_path: "
                f"{settings.sqlite_database_path if settings.sqlite_database_path is not None else 'не sqlite'}"
            )
            print(
                "backup_tool: "
                f"{'доступен' if settings.sqlite_database_path is not None else 'недоступен'}"
            )
            print("export_tool: доступен")
            print("Команда backup: python -m apps.ops backup")
            print("Команда export: python -m apps.ops export")
            return 0

        raise ValueError(f"Неизвестная команда: {args.command}")
    finally:
        await runtime.dispose()


async def main() -> None:
    raise SystemExit(await run_ops(build_parser().parse_args()))
