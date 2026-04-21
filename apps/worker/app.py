from dataclasses import dataclass

from aiogram import Bot

from config.settings import Settings
from core.logging import configure_logging
from services.startup import WorkerStartupService
from storage.database import DatabaseRuntime, bootstrap_database, build_database_runtime


@dataclass(slots=True)
class WorkerRuntime:
    bot: Bot | None
    database: DatabaseRuntime
    service: WorkerStartupService
    settings: Settings


def build_worker_runtime(settings: Settings) -> WorkerRuntime:
    return WorkerRuntime(
        bot=Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None,
        database=build_database_runtime(settings),
        service=WorkerStartupService(),
        settings=settings,
    )


async def run_worker_once(settings: Settings | None = None) -> None:
    runtime = build_worker_runtime(settings or Settings())
    configure_logging(runtime.settings.log_level)

    try:
        await bootstrap_database(runtime.database)
        await runtime.service.run_once(
            session_factory=runtime.database.session_factory,
            bot=runtime.bot,
        )
    finally:
        await runtime.database.dispose()
        if runtime.bot is not None:
            await runtime.bot.session.close()


async def main() -> None:
    await run_worker_once()
