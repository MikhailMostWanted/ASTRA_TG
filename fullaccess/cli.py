from __future__ import annotations

import argparse
import asyncio
import getpass

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.formatter import FullAccessFormatter
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import MessageRepository, SettingRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Локальный helper для experimental full-access Telegram слоя.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Показать состояние full-access слоя.")
    subparsers.add_parser("request-code", help="Локально запросить код входа Telegram.")

    login_parser = subparsers.add_parser(
        "login",
        help="Завершить вход по коду Telegram. При необходимости спросит пароль 2FA локально.",
    )
    login_parser.add_argument("--code", required=True, help="Код, который прислал Telegram.")

    subparsers.add_parser("logout", help="Локально удалить session и pending auth.")
    return parser


async def run_cli(args: argparse.Namespace) -> int:
    settings = Settings()
    runtime = build_database_runtime(settings)
    formatter = FullAccessFormatter()

    try:
        await bootstrap_database(runtime)
        async with runtime.session_factory() as session:
            service = FullAccessAuthService(
                settings=settings,
                setting_repository=SettingRepository(session),
                message_repository=MessageRepository(session),
            )

            if args.command == "status":
                print(formatter.format_status(await service.build_status_report()))
                return 0

            if args.command == "request-code":
                result = await service.begin_login()
                await session.commit()
                print(formatter.format_login(result))
                return 0

            if args.command == "login":
                result = await service.complete_login(
                    args.code,
                    password_callback=lambda: getpass.getpass("Пароль 2FA Telegram: "),
                )
                await session.commit()
                print(formatter.format_login(result))
                return 0

            if args.command == "logout":
                result = await service.logout()
                await session.commit()
                print(formatter.format_logout(result))
                return 0

            raise ValueError(f"Неизвестная команда: {args.command}")
    except ValueError as error:
        print(str(error))
        return 1
    finally:
        await runtime.dispose()


def main() -> int:
    return asyncio.run(run_cli(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
