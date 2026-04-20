import logging
from dataclasses import dataclass

from services.bot_commands import BOT_COMMAND_SPECS
from worker.jobs import list_registered_jobs


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotStartupService:
    def build_start_message(self) -> str:
        return (
            "Astra AFT — Telegram-first слой управления digest-сводками.\n\n"
            "Сейчас основной сценарий такой: выбрать нужные Telegram-источники, "
            "сохранить канал доставки digest и держать конфигурацию в порядке.\n\n"
            "С чего начать:\n"
            "1. Добавить источники через /source_add или посмотреть список через /sources.\n"
            "2. Задать канал доставки через /digest_target.\n"
            "3. После этого вызвать /digest_now и получить первую сводку по уже сохранённым сообщениям."
        )

    def build_help_message(self) -> str:
        command_lines = [
            f"/{spec.command} — {spec.description}"
            for spec in BOT_COMMAND_SPECS
        ]
        return "Команды Astra AFT\n\n" + "\n".join(command_lines)


@dataclass(slots=True, frozen=True)
class WorkerStartupService:
    async def run_once(self) -> None:
        jobs = list_registered_jobs()
        LOGGER.info("Worker bootstrap completed. Registered jobs: %s", list(jobs))
        # TODO: add real background job orchestration when engines are implemented.
