from __future__ import annotations

import argparse
import asyncio
import getpass

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.copy import LOCAL_LOGIN_COMMAND
from fullaccess.formatter import FullAccessFormatter
from fullaccess.models import FullAccessLoginResult
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
        help="Безопасно запросить код и завершить локальный вход. При необходимости спросит пароль 2FA.",
    )
    login_parser.add_argument("--code", required=False, help="Код Telegram. Если не указан, CLI спросит его.")

    subparsers.add_parser("logout", help="Локально удалить session и pending auth.")
    return parser


async def run_cli(args: argparse.Namespace) -> int:
    return await run_fullaccess_command(
        args.command,
        code=getattr(args, "code", None),
    )


async def run_fullaccess_command(
    command: str,
    *,
    code: str | None = None,
) -> int:
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

            if command == "status":
                print(formatter.format_status(await service.build_status_report()))
                return 0

            if command == "request-code":
                result = await service.begin_login()
                await session.commit()
                print(formatter.format_login(result))
                return 0

            if command == "login":
                result = await _run_interactive_login(
                    service=service,
                    formatter=formatter,
                    code=code,
                )
                await session.commit()
                print(formatter.format_login(result))
                return 0

            if command == "logout":
                result = await service.logout()
                await session.commit()
                print(formatter.format_logout(result))
                return 0

            raise ValueError(f"Неизвестная команда: {command}")
    except ValueError as error:
        print(str(error))
        return 1
    finally:
        await runtime.dispose()


async def _run_interactive_login(
    *,
    service: FullAccessAuthService,
    formatter: FullAccessFormatter,
    code: str | None,
) -> FullAccessLoginResult:
    status = await service.build_status_report()
    if status.authorized:
        return FullAccessLoginResult(kind="already_authorized", phone=service.settings.fullaccess_phone)

    if not status.pending_login:
        begin_result = await service.begin_login()
        print(formatter.format_login(begin_result))
        if begin_result.kind == "already_authorized":
            return begin_result

    login_code = (code or input("Код Telegram: ")).strip()
    if not login_code:
        raise ValueError(f"Код не введён. Повтори команду: {LOCAL_LOGIN_COMMAND}")

    return await service.complete_login(
        login_code,
        password_callback=lambda: getpass.getpass("Пароль 2FA Telegram: "),
    )


def main() -> int:
    return asyncio.run(run_cli(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
