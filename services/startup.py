from dataclasses import dataclass

from core.logging import get_logger, log_event
from services.operational_state import OperationalStateService
from services.help_formatter import HelpFormatter
from services.onboarding import OnboardingFormatter
from services.reminder_delivery import ReminderDeliveryService
from services.reminder_formatter import ReminderFormatter
from worker.jobs import list_registered_jobs
from storage.repositories import ReminderRepository, SettingRepository


LOGGER = get_logger(__name__)


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
    ):
        jobs = list_registered_jobs()
        log_event(
            LOGGER,
            20,
            "worker.run.started",
            "Worker run начат.",
            jobs=list(jobs),
        )
        summary = {
            "jobs_total": len(jobs),
            "jobs_failed": 0,
            "processed_count": 0,
            "delivered_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "blocked_count": 0,
        }

        for job_name in jobs:
            if job_name != "reminder_delivery":
                continue

            try:
                async with session_factory() as session:
                    setting_repository = SettingRepository(session)
                    report = await ReminderDeliveryService(
                        setting_repository=setting_repository,
                        reminder_repository=ReminderRepository(session),
                        formatter=ReminderFormatter(),
                    ).deliver_due_reminders(sender=bot)
                    summary["processed_count"] += report.due_count
                    summary["delivered_count"] += report.sent_count
                    summary["failed_count"] += report.failed_count
                    summary["skipped_count"] += report.skipped_count
                    summary["blocked_count"] += report.blocked_count
                    await OperationalStateService(setting_repository).record_worker_run(
                        processed_count=summary["processed_count"],
                        delivered_count=summary["delivered_count"],
                        failed_count=summary["failed_count"],
                        skipped_count=summary["skipped_count"],
                        blocked_count=summary["blocked_count"],
                        jobs_total=summary["jobs_total"],
                        jobs_failed=summary["jobs_failed"],
                    )
                    await session.commit()
            except Exception as error:
                summary["jobs_failed"] += 1
                async with session_factory() as session:
                    await OperationalStateService(SettingRepository(session)).record_error(
                        "worker",
                        message=f"Worker job {job_name} failed: {error}",
                    )
                    await session.commit()
                log_event(
                    LOGGER,
                    40,
                    "worker.job.failed",
                    "Worker job завершился ошибкой.",
                    job_name=job_name,
                    error_type=type(error).__name__,
                )

        log_event(
            LOGGER,
            20,
            "worker.run.completed",
            "Worker run завершён.",
            **summary,
        )
        return summary
