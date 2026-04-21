import logging
from dataclasses import dataclass

from services.reminder_delivery import ReminderDeliveryService
from services.reminder_formatter import ReminderFormatter
from services.bot_commands import BOT_COMMAND_SPECS
from worker.jobs import list_registered_jobs
from storage.repositories import ReminderRepository, SettingRepository


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotStartupService:
    def build_start_message(self) -> str:
        return (
            "Astra AFT — Telegram-first слой управления digest, memory, reply и reminders по локальной БД.\n\n"
            "Сейчас основной сценарий такой: выбрать нужные Telegram-источники, "
            "накопить сообщения, пересобрать память, получить reply-подсказку, при необходимости собрать digest "
            "и подтвердить reminders-кандидаты.\n\n"
            "С чего начать:\n"
            "1. Добавить источники через /source_add или посмотреть список через /sources.\n"
            "2. Накопить сообщения из разрешённых чатов.\n"
            "3. Вызвать /memory_rebuild и проверить /chat_memory или /person_memory.\n"
            "4. Вызвать /examples_rebuild, чтобы собрать локальные reply examples.\n"
            "5. Для подсказки ответа вызвать /reply <chat_id|@username> или, если provider включён, /reply_llm <chat_id|@username>.\n"
            "6. Для reminders вызвать /reminders_scan и подтвердить карточки.\n"
            "7. Задать канал доставки через /digest_target и вызвать /digest_now или /digest_llm.\n"
            "8. Проверить optional provider layer через /provider_status."
        )

    def build_help_message(self) -> str:
        command_lines = [
            f"/{spec.command} — {spec.description}"
            for spec in BOT_COMMAND_SPECS
        ]
        return "Команды Astra AFT\n\n" + "\n".join(command_lines)


@dataclass(slots=True, frozen=True)
class WorkerStartupService:
    async def run_once(
        self,
        *,
        session_factory,
        bot,
    ) -> None:
        jobs = list_registered_jobs()
        LOGGER.info("Worker bootstrap completed. Registered jobs: %s", list(jobs))
        async with session_factory() as session:
            report = await ReminderDeliveryService(
                setting_repository=SettingRepository(session),
                reminder_repository=ReminderRepository(session),
                formatter=ReminderFormatter(),
            ).deliver_due_reminders(sender=bot)
            await session.commit()
        LOGGER.info(
            "Reminder delivery run finished. due=%s sent=%s blocked=%s",
            report.due_count,
            report.sent_count,
            report.blocked_count,
        )
