import logging
from dataclasses import dataclass

from worker.jobs import list_registered_jobs


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotStartupService:
    def build_start_message(self) -> str:
        return (
            "Astra AFT skeleton is running.\n"
            "TODO: digest summaries, memory, reply suggestions, and reminders "
            "are not implemented yet."
        )


@dataclass(slots=True, frozen=True)
class WorkerStartupService:
    async def run_once(self) -> None:
        jobs = list_registered_jobs()
        LOGGER.info("Worker bootstrap completed. Registered jobs: %s", list(jobs))
        # TODO: add real background job orchestration when engines are implemented.
