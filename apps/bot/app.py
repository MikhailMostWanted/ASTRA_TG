from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from bot.router import build_dispatcher
from config.settings import Settings
from core.logging import configure_logging
from storage.database import DatabaseRuntime, bootstrap_database, build_database_runtime


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
    runtime = build_bot_runtime(settings or Settings())
    configure_logging(runtime.settings.log_level)

    try:
        await bootstrap_database(runtime.database)
        await runtime.dispatcher.start_polling(runtime.bot)
    finally:
        await runtime.database.dispose()
        await runtime.bot.session.close()


async def main() -> None:
    await run_bot()
