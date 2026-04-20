from dataclasses import dataclass

from config.settings import Settings
from core.logging import configure_logging
from services.startup import WorkerStartupService
from storage.database import DatabaseRuntime, bootstrap_database, build_database_runtime


@dataclass(slots=True)
class WorkerRuntime:
    database: DatabaseRuntime
    service: WorkerStartupService
    settings: Settings


def build_worker_runtime(settings: Settings) -> WorkerRuntime:
    return WorkerRuntime(
        database=build_database_runtime(settings),
        service=WorkerStartupService(),
        settings=settings,
    )


async def run_worker_once(settings: Settings | None = None) -> None:
    runtime = build_worker_runtime(settings or Settings())
    configure_logging(runtime.settings.log_level)

    try:
        await bootstrap_database(runtime.database)
        await runtime.service.run_once()
    finally:
        await runtime.database.dispose()


async def main() -> None:
    await run_worker_once()
