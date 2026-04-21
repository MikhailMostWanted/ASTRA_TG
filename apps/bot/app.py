from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.router import build_dispatcher
from config.settings import Settings
from core.logging import configure_logging, get_logger, log_event
from services.bot_commands import build_bot_commands
from services.startup_validation import StartupValidationService
from storage.database import DatabaseRuntime, bootstrap_database, build_database_runtime


LOGGER = get_logger(__name__)


class BotCommandsConfiguratorProtocol(Protocol):
    async def set_my_commands(self, commands: list[BotCommand]) -> object: ...


@dataclass(slots=True)
class BotRuntime:
    bot: Bot
    dispatcher: Dispatcher
    database: DatabaseRuntime
    settings: Settings


def build_bot_runtime(settings: Settings) -> BotRuntime:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required to run the bot app.")

    return BotRuntime(
        bot=Bot(token=settings.telegram_bot_token),
        dispatcher=build_dispatcher(),
        database=build_database_runtime(settings),
        settings=settings,
    )


async def run_bot(settings: Settings | None = None) -> None:
    effective_settings = settings or Settings()
    configure_logging(effective_settings.log_level)

    try:
        runtime = build_bot_runtime(effective_settings)
    except RuntimeError as error:
        log_event(
            LOGGER,
            40,
            "bot.startup.invalid_config",
            "Bot не может стартовать из-за критичной конфигурации.",
            error=str(error),
        )
        raise

    log_event(
        LOGGER,
        20,
        "bot.startup.started",
        "Bot startup начат.",
    )

    try:
        await bootstrap_database(runtime.database)
        validator = StartupValidationService(
            settings=runtime.settings,
            session_factory=runtime.database.session_factory,
        )
        report = await validator.build_bot_report()
        await validator.store_report(report)
        log_event(
            LOGGER,
            20,
            "bot.startup.validation",
            "Startup self-check для bot завершён.",
            can_start=report.can_start,
            warnings=len(report.warnings),
            critical_issues=len(report.critical_issues),
        )
        if not report.can_start:
            raise RuntimeError("; ".join(report.critical_issues))
        await configure_bot_commands(runtime.bot)
        log_event(
            LOGGER,
            20,
            "bot.polling.started",
            "Запущен bot polling.",
        )
        await runtime.dispatcher.start_polling(
            runtime.bot,
            session_factory=runtime.database.session_factory,
        )
    finally:
        log_event(
            LOGGER,
            20,
            "bot.shutdown",
            "Bot runtime завершает работу.",
        )
        await runtime.database.dispose()
        await runtime.bot.session.close()


async def main() -> None:
    await run_bot()


async def configure_bot_commands(bot: BotCommandsConfiguratorProtocol) -> None:
    await bot.set_my_commands(build_bot_commands())
