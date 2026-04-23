from dataclasses import dataclass

from config.settings import Settings
from core.logging import get_logger, log_event
from fullaccess.auth import FullAccessAuthService
from fullaccess.send import FullAccessSendService
from services.autopilot import AutopilotService
from services.operational_state import OperationalStateService
from services.help_formatter import HelpFormatter
from services.onboarding import OnboardingFormatter
from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_guardrails import PersonaGuardrails
from services.providers.manager import ProviderManager
from services.providers.reply_refiner import ReplyLLMRefiner
from services.reminder_delivery import ReminderDeliveryService
from services.reminder_formatter import ReminderFormatter
from services.reply_classifier import ReplyClassifier
from services.reply_context_builder import ReplyContextBuilder
from services.reply_engine import ReplyEngineService
from services.reply_examples_retriever import ReplyExamplesRetriever
from services.reply_strategy import ReplyStrategyResolver
from services.style_adapter import StyleAdapter
from services.style_selector import StyleSelectorService
from services.workflow_journal import WorkflowJournalService
from worker.jobs import list_registered_jobs
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReminderRepository,
    ReplyExampleRepository,
    SettingRepository,
    StyleProfileRepository,
)


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
            try:
                async with session_factory() as session:
                    setting_repository = SettingRepository(session)
                    if job_name == "reminder_delivery":
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
                    elif job_name == "autopilot":
                        report = await _run_autopilot_job(session=session)
                        summary["processed_count"] += report["processed_count"]
                        summary["delivered_count"] += report["sent_count"]
                        summary["skipped_count"] += report["skipped_count"]
                        summary["blocked_count"] += report["blocked_count"]
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


async def _run_autopilot_job(*, session) -> dict[str, int]:
    setting_repository = SettingRepository(session)
    chat_repository = ChatRepository(session)
    message_repository = MessageRepository(session)
    settings = Settings()
    autopilot = AutopilotService(
        chat_repository=chat_repository,
        setting_repository=setting_repository,
        send_service=FullAccessSendService(
            settings=settings,
            chat_repository=chat_repository,
            message_repository=message_repository,
            setting_repository=setting_repository,
        ),
        journal=WorkflowJournalService(setting_repository),
    )
    global_settings = await autopilot.get_global_settings()
    if not global_settings.master_enabled:
        return {
            "processed_count": 0,
            "sent_count": 0,
            "skipped_count": 0,
            "blocked_count": 0,
        }

    fullaccess_status = await FullAccessAuthService(
        settings=settings,
        setting_repository=setting_repository,
        message_repository=message_repository,
    ).build_status_report()
    reply_service = _build_reply_service(
        session=session,
        settings=settings,
        chat_repository=chat_repository,
        message_repository=message_repository,
        setting_repository=setting_repository,
    )

    processed_count = 0
    sent_count = 0
    skipped_count = 0
    blocked_count = 0
    for chat in await chat_repository.list_enabled_chats():
        if not chat.reply_assist_enabled and not chat.auto_reply_mode:
            continue
        processed_count += 1
        reply_result = await reply_service.build_reply(_build_chat_reference(chat))
        result = await autopilot.run_for_chat(
            chat=chat,
            reply_result=reply_result,
            actor="worker",
            write_ready=fullaccess_status.ready_for_manual_send,
        )
        if result.send_result is not None:
            sent_count += 1
        elif result.decision.allowed:
            skipped_count += 1
        else:
            blocked_count += 1

    return {
        "processed_count": processed_count,
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "blocked_count": blocked_count,
    }


def _build_reply_service(
    *,
    session,
    settings,
    chat_repository: ChatRepository,
    message_repository: MessageRepository,
    setting_repository: SettingRepository,
) -> ReplyEngineService:
    chat_memory_repository = ChatMemoryRepository(session)
    person_memory_repository = PersonMemoryRepository(session)
    provider_manager = ProviderManager.from_settings(
        settings,
        setting_repository=setting_repository,
    )
    return ReplyEngineService(
        chat_repository=chat_repository,
        message_repository=message_repository,
        chat_memory_repository=chat_memory_repository,
        person_memory_repository=person_memory_repository,
        context_builder=ReplyContextBuilder(
            message_repository=message_repository,
            chat_memory_repository=chat_memory_repository,
            person_memory_repository=person_memory_repository,
        ),
        classifier=ReplyClassifier(),
        strategy_resolver=ReplyStrategyResolver(),
        style_selector=StyleSelectorService(
            style_profile_repository=StyleProfileRepository(session),
            chat_style_override_repository=ChatStyleOverrideRepository(session),
            chat_memory_repository=chat_memory_repository,
            person_memory_repository=person_memory_repository,
        ),
        style_adapter=StyleAdapter(),
        persona_core_service=PersonaCoreService(setting_repository),
        persona_adapter=PersonaAdapter(),
        persona_guardrails=PersonaGuardrails(),
        reply_examples_retriever=ReplyExamplesRetriever(
            reply_example_repository=ReplyExampleRepository(session),
        ),
        reply_refiner=ReplyLLMRefiner(provider_manager=provider_manager),
        setting_repository=setting_repository,
    )


def _build_chat_reference(chat) -> str:
    if getattr(chat, "handle", None):
        return f"@{chat.handle}"
    return str(chat.telegram_chat_id)
