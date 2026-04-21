import logging
from dataclasses import dataclass

from services.help_formatter import HelpFormatter
from services.onboarding import OnboardingFormatter
from services.reminder_delivery import ReminderDeliveryService
from services.reminder_formatter import ReminderFormatter
from worker.jobs import list_registered_jobs
from storage.repositories import ReminderRepository, SettingRepository


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BotStartupService:
    def build_start_message(self) -> str:
        return OnboardingFormatter().build_start_message()

    def build_onboarding_message(self) -> str:
        return OnboardingFormatter().build_message()

    def build_help_message(self) -> str:
        return HelpFormatter().build_message()


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
