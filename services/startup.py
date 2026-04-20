import logging
from dataclasses import dataclass

from services.bot_commands import BOT_COMMAND_SPECS
from worker.jobs import list_registered_jobs


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotStartupService:
    def build_start_message(self) -> str:
        return (
            "Astra AFT — Telegram-first слой управления digest и memory по локальной БД.\n\n"
            "Сейчас основной сценарий такой: выбрать нужные Telegram-источники, "
            "накопить сообщения, пересобрать память и при необходимости собрать digest.\n\n"
            "С чего начать:\n"
            "1. Добавить источники через /source_add или посмотреть список через /sources.\n"
            "2. Накопить сообщения из разрешённых чатов.\n"
            "3. Вызвать /memory_rebuild и проверить /chat_memory или /person_memory.\n"
            "4. Задать канал доставки через /digest_target и вызвать /digest_now."
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
