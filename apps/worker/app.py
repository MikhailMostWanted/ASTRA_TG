from dataclasses import dataclass

from aiogram import Bot

from config.settings import Settings
from core.logging import configure_logging, get_logger, log_event
from services.startup import WorkerStartupService
from services.startup_validation import StartupValidationService
from storage.database import DatabaseRuntime, bootstrap_database, build_database_runtime


LOGGER = get_logger(__name__)


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
        log_event(
            LOGGER,
            20,
            "worker.startup.started",
            "Worker startup начат.",
        )
        await bootstrap_database(runtime.database)
        validator = StartupValidationService(
            settings=runtime.settings,
            session_factory=runtime.database.session_factory,
        )
        report = await validator.build_worker_report()
        await validator.store_report(report)
        log_event(
            LOGGER,
            20,
            "worker.startup.validation",
            "Startup self-check для worker завершён.",
            can_start=report.can_start,
            warnings=len(report.warnings),
            critical_issues=len(report.critical_issues),
        )
        if not report.can_start:
            raise RuntimeError("; ".join(report.critical_issues))
        await runtime.service.run_once(
            session_factory=runtime.database.session_factory,
            bot=runtime.bot,
        )
    finally:
        log_event(
            LOGGER,
            20,
            "worker.shutdown",
            "Worker runtime завершает работу.",
        )
        await runtime.database.dispose()
        if runtime.bot is not None:
            await runtime.bot.session.close()


async def main() -> None:
    await run_worker_once()
