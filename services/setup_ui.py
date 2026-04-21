from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.formatter import FullAccessFormatter
from fullaccess.sync import FullAccessSyncService
from services.chat_memory_builder import ChatMemoryBuilder
from services.digest_builder import DigestBuilder
from services.digest_engine import DigestEngineService, DigestPublisherService, MessageSenderProtocol
from services.digest_formatter import DigestFormatter
from services.inline_navigation import (
    SCREEN_CHECKLIST,
    SCREEN_DIGEST,
    SCREEN_DOCTOR,
    SCREEN_FULLACCESS,
    SCREEN_FULLACCESS_CHATS,
    SCREEN_HOME,
    SCREEN_MEMORY,
    SCREEN_MEMORY_PICK,
    SCREEN_OPS,
    SCREEN_PROVIDER,
    SCREEN_REMINDERS,
    SCREEN_REPLY,
    SCREEN_REPLY_HELP,
    SCREEN_REPLY_PICK,
    SCREEN_SOURCES,
    SCREEN_SOURCES_HELP,
    SCREEN_STATUS,
    digest_run_route,
    fullaccess_chat_route,
    fullaccess_chats_route,
    memory_rebuild_route,
    memory_chat_route,
    memory_pick_route,
    reminders_list_route,
    reminders_scan_route,
    reminders_tasks_route,
    reply_chat_route,
    reply_examples_route,
    reply_help_route,
    reply_pick_route,
    screen_route,
    source_toggle_route,
    style_status_route,
    sources_help_route,
)
from services.memory_builder import MemoryRebuildResult, MemoryService
from services.memory_formatter import MemoryFormatter
from services.people_memory_builder import PeopleMemoryBuilder
from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_guardrails import PersonaGuardrails
from services.providers.digest_refiner import DigestLLMRefiner
from services.providers.manager import ProviderManager
from services.providers.reply_refiner import ReplyLLMRefiner
from services.reply_classifier import ReplyClassifier
from services.reply_context_builder import ReplyContextBuilder
from services.reply_engine import ReplyEngineService
from services.reply_examples_formatter import ReplyExamplesFormatter
from services.reply_examples_retriever import ReplyExamplesRetriever
from services.reply_formatter import ReplyFormatter
from services.reply_models import ReplyContextIssue
from services.reply_strategy import ReplyStrategyResolver
from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter
from services.reminder_models import ReminderScanResult
from services.reminder_service import ReminderService
from services.render_cards import (
    MARKER_EXP,
    MARKER_OFF,
    MARKER_OK,
    MARKER_OPT,
    MARKER_WARN,
    RenderedCard,
    compact_text,
    format_status_line,
    ready_marker,
    render_help_card,
    render_home_card,
    render_overview_card,
    render_text_card,
    state_shell_lines,
)
from services.source_registry import SourceRegistryService
from services.status_summary import BotStatusService
from services.style_adapter import StyleAdapter
from services.style_formatter import StyleFormatter
from services.style_profiles import StyleProfileService
from services.style_selector import StyleSelectorService
from services.system_health import SystemHealthService
from services.system_readiness import OperationalCheck, OperationalReport
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReplyExampleRepository,
    ReminderRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
    TaskRepository,
)


STYLE_READY_PROFILE_COUNT = 6


@dataclass(slots=True)
class SetupUIService:
    status_service: BotStatusService
    chat_repository: ChatRepository
    message_repository: MessageRepository
    digest_repository: DigestRepository
    setting_repository: SettingRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    style_profile_repository: StyleProfileRepository
    chat_style_override_repository: ChatStyleOverrideRepository
    reply_example_repository: ReplyExampleRepository
    memory_service: MemoryService
    reminder_service: ReminderService
    fullaccess_auth_service: FullAccessAuthService

    @classmethod
    def from_session(cls, session: AsyncSession) -> "SetupUIService":
        settings = Settings()
        chat_repository = ChatRepository(session)
        message_repository = MessageRepository(session)
        setting_repository = SettingRepository(session)
        digest_repository = DigestRepository(session)
        chat_memory_repository = ChatMemoryRepository(session)
        person_memory_repository = PersonMemoryRepository(session)
        style_profile_repository = StyleProfileRepository(session)
        chat_style_override_repository = ChatStyleOverrideRepository(session)
        task_repository = TaskRepository(session)
        reminder_repository = ReminderRepository(session)
        reply_example_repository = ReplyExampleRepository(session)
        fullaccess_auth_service = FullAccessAuthService(
            settings=settings,
            setting_repository=setting_repository,
            message_repository=message_repository,
        )
        provider_manager = ProviderManager.from_settings(settings)
        if isinstance(provider_manager, ProviderManager):
            provider_manager.setting_repository = setting_repository

        return cls(
            status_service=BotStatusService(
                settings=settings,
                chat_repository=chat_repository,
                setting_repository=setting_repository,
                system_repository=SystemRepository(session),
                message_repository=message_repository,
                digest_repository=digest_repository,
                chat_memory_repository=chat_memory_repository,
                person_memory_repository=person_memory_repository,
                style_profile_repository=style_profile_repository,
                chat_style_override_repository=chat_style_override_repository,
                task_repository=task_repository,
                reminder_repository=reminder_repository,
                reply_example_repository=reply_example_repository,
                provider_manager=provider_manager,
                fullaccess_auth_service=fullaccess_auth_service,
            ),
            chat_repository=chat_repository,
            message_repository=message_repository,
            digest_repository=digest_repository,
            setting_repository=setting_repository,
            chat_memory_repository=chat_memory_repository,
            person_memory_repository=person_memory_repository,
            style_profile_repository=style_profile_repository,
            chat_style_override_repository=chat_style_override_repository,
            reply_example_repository=reply_example_repository,
            memory_service=MemoryService(
                chat_repository=chat_repository,
                message_repository=message_repository,
                digest_repository=digest_repository,
                setting_repository=setting_repository,
                chat_memory_repository=chat_memory_repository,
                person_memory_repository=person_memory_repository,
                chat_builder=ChatMemoryBuilder(),
                people_builder=PeopleMemoryBuilder(),
                formatter=MemoryFormatter(),
            ),
            reminder_service=ReminderService(
                chat_repository=chat_repository,
                message_repository=message_repository,
                chat_memory_repository=chat_memory_repository,
                setting_repository=setting_repository,
                task_repository=task_repository,
                reminder_repository=reminder_repository,
                extractor=ReminderExtractor(),
                formatter=ReminderFormatter(),
            ),
            fullaccess_auth_service=fullaccess_auth_service,
        )

    async def build_screen(self, screen: str) -> RenderedCard:
        if screen == SCREEN_HOME:
            return await self._build_home_card()
        if screen == SCREEN_STATUS:
            return await self._build_status_card()
        if screen == SCREEN_CHECKLIST:
            return await self._build_checklist_card()
        if screen == SCREEN_DOCTOR:
            return await self._build_doctor_card()
        if screen == SCREEN_SOURCES:
            return await self._build_sources_card()
        if screen == SCREEN_SOURCES_HELP:
            return self._build_sources_help_card()
        if screen == SCREEN_DIGEST:
            return await self._build_digest_card()
        if screen == SCREEN_MEMORY:
            return await self._build_memory_card()
        if screen == SCREEN_MEMORY_PICK:
            return await self._build_memory_picker_card()
        if screen == SCREEN_REPLY:
            return await self._build_reply_card()
        if screen == SCREEN_REPLY_PICK:
            return await self._build_reply_picker_card()
        if screen == SCREEN_REPLY_HELP:
            return self._build_reply_help_card()
        if screen == SCREEN_REMINDERS:
            return await self._build_reminders_card()
        if screen == SCREEN_PROVIDER:
            return await self._build_provider_card()
        if screen == SCREEN_FULLACCESS:
            return await self._build_fullaccess_card()
        if screen == SCREEN_FULLACCESS_CHATS:
            return await self._build_fullaccess_chats_card()
        if screen == SCREEN_OPS:
            return await self._build_ops_card()
        raise ValueError(f"Неизвестный setup-экран: {screen}")

    async def build_start_keyboard(self, *, owner_chat_known: bool) -> InlineKeyboardMarkup:
        report = await self._build_report()
        primary_label = "Открыть центр управления" if owner_chat_known and not _is_cold_start(report) else "Начать настройку"
        from services.render_cards import build_start_keyboard

        return build_start_keyboard(primary_label=primary_label)

    async def run_digest(
        self,
        *,
        window_argument: str,
        preview_chat_id: int,
        sender: MessageSenderProtocol,
    ) -> RenderedCard:
        plan = await self._build_digest_service().build_manual_digest(window_argument)
        publish_result = await DigestPublisherService(self.digest_repository).publish(
            plan=plan,
            preview_chat_id=preview_chat_id,
            sender=sender,
        )
        return render_text_card(
            title="Astra AFT / Digest / Результат",
            lines=DigestFormatter().format_inline_result(
                plan=plan,
                notice=publish_result.notice,
            ).splitlines(),
            rows=[
                [("Собрать 24h", digest_run_route("24h")), ("Собрать 12h", digest_run_route("12h"))],
            ],
            back_screen=SCREEN_DIGEST,
            current_screen=SCREEN_DIGEST,
        )

    async def rebuild_memory(self) -> MemoryRebuildResult:
        return await self.memory_service.rebuild()

    async def run_reminders_scan(self, *, window_argument: str) -> ReminderScanResult:
        return await self.reminder_service.scan(
            window_argument=window_argument,
            source_reference=None,
        )

    async def build_tasks_message(self) -> str:
        return await self.reminder_service.build_tasks_message()

    async def build_reminders_message(self) -> str:
        return await self.reminder_service.build_reminders_message()

    async def _build_home_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        detail_lines = [
            _line(
                _ok_warn(facts.active_sources > 0 and facts.has_messages),
                "Источники",
                f"{facts.active_sources} активных, с данными {facts.chats_with_data}/{facts.total_sources}",
            ),
            _line(
                _ok_warn(
                    facts.digest_sources > 0
                    and facts.digest_target_configured
                    and facts.digest_window_messages > 0
                ),
                "Digest",
                f"target: {facts.digest_target_label or 'не задан'}, окно {facts.digest_window_label}: {facts.digest_window_messages}",
            ),
            _line(
                _ok_warn(facts.has_memory_cards),
                "Memory",
                f"чаты {facts.chat_memory_cards}, люди {facts.person_memory_cards}",
            ),
            _line(
                _ok_warn(_find_check(report.layers, "reply").ready),
                "Reply",
                f"ready chats {facts.reply_ready_chats}, few-shot: {_yes_no(facts.reply_examples > 0)}",
            ),
            _compose_reminders_line(report),
            _compose_provider_line(report),
            _compose_fullaccess_line(report),
            _compose_ops_line(facts),
        ]
        return render_home_card(
            title="Astra AFT / Setup",
            summary_lines=[
                f"Готово: {report.ready_check_count}/{report.total_check_count}",
                f"Основной контур: {_yes_no(_core_path_ready(report))}",
            ],
            detail_lines=detail_lines,
            next_step=_build_next_step(report),
            rows=[
                [
                    ("Статус", screen_route(SCREEN_STATUS)),
                    ("Чеклист", screen_route(SCREEN_CHECKLIST)),
                    ("Диагностика", screen_route(SCREEN_DOCTOR)),
                ],
                [
                    ("Источники", screen_route(SCREEN_SOURCES)),
                    ("Дайджест", screen_route(SCREEN_DIGEST)),
                    ("Память", screen_route(SCREEN_MEMORY)),
                ],
                [
                    ("Ответы", screen_route(SCREEN_REPLY)),
                    ("Напоминания", screen_route(SCREEN_REMINDERS)),
                ],
                [
                    ("Provider", screen_route(SCREEN_PROVIDER)),
                    ("Full-access", screen_route(SCREEN_FULLACCESS)),
                    ("Ops", screen_route(SCREEN_OPS)),
                ],
                [("Обновить", "ux:refresh:home")],
            ],
        )

    async def _build_status_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        detail_lines = [
            _line(
                _ok_warn(facts.active_sources > 0 and facts.has_messages),
                "Источники",
                f"{facts.active_sources} активных, сообщений {facts.total_messages}, с данными {facts.chats_with_data}",
            ),
            _line(
                _ok_warn(
                    facts.digest_sources > 0
                    and facts.digest_target_configured
                    and facts.digest_window_messages > 0
                ),
                "Digest",
                f"target: {facts.digest_target_label or 'не задан'}, данных 24h: {facts.digest_window_messages}",
            ),
            _line(
                _ok_warn(facts.has_memory_cards),
                "Memory",
                f"чаты {facts.chat_memory_cards}, люди {facts.person_memory_cards}, rebuild: {_format_timestamp(facts.last_memory_rebuild_at)}",
            ),
            _line(
                _ok_warn(_find_check(report.layers, "reply").ready),
                "Reply",
                f"ready chats {facts.reply_ready_chats}, examples {facts.reply_examples}, style {facts.style_profiles}/{STYLE_READY_PROFILE_COUNT}",
            ),
            _compose_reminders_line(report),
            _compose_provider_line(report),
            _compose_fullaccess_line(report),
            _compose_ops_line(facts),
        ]
        rows = [[("Чеклист", screen_route(SCREEN_CHECKLIST)), ("Диагностика", screen_route(SCREEN_DOCTOR))]]
        navigation_button = _build_navigation_button(report)
        if navigation_button is not None:
            rows.append([navigation_button])
        return render_overview_card(
            title="Astra AFT / Status",
            summary_lines=[
                f"Готово: {report.ready_check_count}/{report.total_check_count}",
                f"Предупреждений: {len(report.warnings)}",
            ],
            detail_lines=detail_lines,
            next_step=_build_next_step(report),
            rows=rows,
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_STATUS,
        )

    async def _build_checklist_card(self) -> RenderedCard:
        report = await self._build_report()
        detail_lines = [
            _compose_checklist_line(index=index, item=item)
            for index, item in enumerate(report.checklist, start=1)
        ]
        rows = [[("Статус", screen_route(SCREEN_STATUS)), ("Диагностика", screen_route(SCREEN_DOCTOR))]]
        navigation_button = _build_navigation_button(report)
        if navigation_button is not None:
            rows.append([navigation_button])
        return render_overview_card(
            title="Astra AFT / Checklist",
            summary_lines=[
                f"Готово: {report.ready_check_count}/{report.total_check_count}",
                f"Первый незакрытый шаг: {_first_unready_title(report)}",
            ],
            detail_lines=detail_lines,
            next_step=_build_next_step(report),
            rows=rows,
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_CHECKLIST,
        )

    async def _build_doctor_card(self) -> RenderedCard:
        report = await self._build_report()
        doctor = SystemHealthService().build_report(report)
        detail_lines = [
            "ОК",
            *[f"{MARKER_OK} {compact_text(item, limit=82)}" for item in doctor.ok_items[:3]],
            "",
            "Предупреждения",
            *[
                f"{_doctor_warning_marker(item)} {compact_text(item, limit=82)}"
                for item in doctor.warnings[:4]
            ],
        ]
        hidden_warning_count = max(len(doctor.warnings) - 4, 0)
        if hidden_warning_count:
            detail_lines.append(f"{MARKER_WARN} Ещё предупреждений: {hidden_warning_count}")
        detail_lines.extend(["", "Операционный слой"])
        detail_lines.append(_compose_ops_line(report.facts))
        rows = [[("Статус", screen_route(SCREEN_STATUS)), ("Чеклист", screen_route(SCREEN_CHECKLIST))]]
        return render_overview_card(
            title="Astra AFT / Doctor",
            summary_lines=[
                f"ОК-пунктов: {len(doctor.ok_items)}",
                f"Предупреждений: {len(doctor.warnings)}",
            ],
            detail_lines=detail_lines,
            next_step=compact_text(
                doctor.next_steps[0] if doctor.next_steps else _build_next_step(report),
                limit=96,
            ),
            rows=rows,
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_DOCTOR,
        )

    async def _build_sources_card(self) -> RenderedCard:
        report = await self._build_report()
        chats = await self.chat_repository.list_chats()
        message_counts = await self.message_repository.count_messages_by_chat()
        detail_lines = []
        for chat in chats[:4]:
            marker = MARKER_OK if chat.is_enabled and message_counts.get(chat.id, 0) > 0 else MARKER_OFF if not chat.is_enabled else MARKER_WARN
            source_flags = []
            if chat.exclude_from_digest:
                source_flags.append("без digest")
            if chat.exclude_from_memory:
                source_flags.append("без memory")
            flags = f", {', '.join(source_flags)}" if source_flags else ""
            detail_lines.append(
                f"{marker} {chat.title or chat.telegram_chat_id}: {message_counts.get(chat.id, 0)} сообщений{flags}"
            )
        if not detail_lines:
            detail_lines.extend(
                state_shell_lines(
                    marker=MARKER_WARN,
                    status="Источники не добавлены",
                    meaning="Astra пока не получает сообщения для digest, memory и reply.",
                    next_step="/source_add <chat_id|@username>",
                )
            )
        if len(chats) > 4:
            detail_lines.append(f"{MARKER_OK} Ещё источников: {len(chats) - 4}")
        rows = [[("Как добавить", sources_help_route())]]
        for chat in chats[:3]:
            rows.append(
                [
                    (
                        _source_toggle_button_label(chat),
                        source_toggle_route(_chat_route_reference(chat)),
                    )
                ]
            )

        return render_overview_card(
            title="Astra AFT / Sources",
            summary_lines=[
                f"Всего источников: {report.facts.total_sources}",
                f"Активных: {report.facts.active_sources}",
                f"С данными: {report.facts.chats_with_data}",
            ],
            detail_lines=detail_lines,
            next_step=_build_sources_next_step(report),
            rows=rows,
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_SOURCES,
        )

    def _build_sources_help_card(self) -> RenderedCard:
        return render_help_card(
            title="Astra AFT / Sources / Как добавить",
            lines=[
                "1. /source_add @username для публичного чата или канала.",
                "2. /source_add -1001234567890 для прямого chat_id.",
                "3. Перешли сообщение из нужного чата и вызови /source_add.",
                "4. Ответь на сообщение из нужного чата и вызови /source_add.",
            ],
            next_step="/source_add <chat_id|@username>",
            rows=[[("Назад", screen_route(SCREEN_SOURCES)), ("Домой", screen_route(SCREEN_HOME))]],
        )

    async def _build_digest_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        detail_lines = [
            _line(_ok_warn(facts.digest_target_configured), "Target", facts.digest_target_label or "не задан"),
            _line(_ok_warn(facts.digest_window_messages > 0), "Данные", f"в {facts.digest_window_label}: {facts.digest_window_messages}"),
            _line(_ok_warn(facts.digest_sources > 0), "Источники", f"digest-источников: {facts.digest_sources}"),
            _compose_provider_digest_line(report),
            f"{MARKER_OK} Digest читает локальную БД и показывает preview в текущем чате.",
        ]
        return render_overview_card(
            title="Astra AFT / Digest",
            summary_lines=[
                f"Канал доставки: {facts.digest_target_label or 'не задан'}",
                f"Окно по умолчанию: {facts.digest_window_label}",
            ],
            detail_lines=detail_lines,
            next_step=_build_digest_next_step(report),
            rows=[
                [
                    ("Собрать 24h", digest_run_route("24h")),
                    ("Собрать 12h", digest_run_route("12h")),
                ]
            ],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_DIGEST,
        )

    async def _build_memory_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        detail_lines = [
            _line(_ok_warn(facts.chat_memory_cards > 0), "Карты чатов", str(facts.chat_memory_cards)),
            _line(MARKER_OK if facts.person_memory_cards > 0 else MARKER_OFF, "Карты людей", str(facts.person_memory_cards)),
            _line(_ok_warn(facts.last_memory_rebuild_at is not None), "Последний rebuild", _format_timestamp(facts.last_memory_rebuild_at)),
            f"{MARKER_OK} Память строится только по локальной SQLite-БД.",
        ]
        return render_overview_card(
            title="Astra AFT / Memory",
            summary_lines=[
                f"Карт чатов: {facts.chat_memory_cards}",
                f"Карт людей: {facts.person_memory_cards}",
            ],
            detail_lines=detail_lines,
            next_step=_build_memory_next_step(report),
            rows=[
                [("Пересобрать", memory_rebuild_route()), ("Чаты", screen_route(SCREEN_MEMORY_PICK))]
            ],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_MEMORY,
        )

    async def _build_reply_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        detail_lines = [
            _line(_ok_warn(facts.reply_ready_chats > 0), "Готовые чаты", str(facts.reply_ready_chats)),
            _line(
                _ok_warn(facts.reply_examples > 0),
                "Похожие ответы",
                f"{facts.reply_examples} примеров в {facts.reply_example_chats} чатах",
            ),
            _line(
                _ok_warn(facts.style_profiles >= STYLE_READY_PROFILE_COUNT),
                "Стиль",
                f"{facts.style_profiles} профилей, overrides {facts.style_overrides}",
            ),
            _compose_persona_line(facts),
            _compose_provider_reply_line(report),
        ]
        return render_overview_card(
            title="Astra AFT / Reply",
            summary_lines=[
                f"Готовых чатов: {facts.reply_ready_chats}",
                f"Похожие ответы: {_yes_no(facts.reply_examples > 0)}",
            ],
            detail_lines=detail_lines,
            next_step=_build_reply_next_step(report),
            rows=[[("Выбрать чат", reply_pick_route()), ("Как использовать", reply_help_route())]],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_REPLY,
        )

    def _build_reply_help_card(self) -> RenderedCard:
        return render_help_card(
            title="Astra AFT / Reply / Как использовать",
            lines=[
                "Слой ответов работает по локальному контексту, а не по живому Telegram.",
                "Базовый запуск: /reply <chat_id|@username>.",
                "LLM-версия: /reply_llm <chat_id|@username>.",
                "Похожие ответы: /reply_examples <chat_id|@username>.",
            ],
            next_step="/reply <chat_id|@username>",
            rows=[[("Назад", screen_route(SCREEN_REPLY)), ("Домой", screen_route(SCREEN_HOME))]],
        )

    async def _build_reminders_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        detail_lines = [
            _line(
                _ok_warn(facts.owner_chat_id is not None),
                "Личный чат владельца",
                str(facts.owner_chat_id) if facts.owner_chat_id is not None else "не задан",
            ),
            _line(MARKER_OK if facts.candidate_tasks > 0 else MARKER_OFF, "Кандидаты", str(facts.candidate_tasks)),
            _line(MARKER_OK if facts.confirmed_tasks > 0 else MARKER_OFF, "Активные задачи", str(facts.confirmed_tasks)),
            _line(MARKER_OK if facts.active_reminders > 0 else MARKER_OFF, "Активные напоминания", str(facts.active_reminders)),
            _line(_ok_warn(facts.reminders_worker_ready), "Фоновая доставка", _yes_no(facts.reminders_worker_ready)),
            _line(
                _ok_warn(facts.last_reminder_notification is not None),
                "Последняя доставка",
                _format_timestamp(facts.last_reminder_notification),
            ),
        ]
        return render_overview_card(
            title="Astra AFT / Reminders",
            summary_lines=[
                f"Кандидатов: {facts.candidate_tasks}",
                f"Активных задач: {facts.confirmed_tasks}",
                f"Активных напоминаний: {facts.active_reminders}",
            ],
            detail_lines=detail_lines,
            next_step=_build_reminders_next_step(report),
            rows=[
                [("Скан 12h", reminders_scan_route("12h")), ("Скан 24h", reminders_scan_route("24h"))],
                [("Задачи", reminders_tasks_route()), ("Напоминания", reminders_list_route())],
            ],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_REMINDERS,
        )

    async def _build_provider_card(self) -> RenderedCard:
        status = await self._get_provider_status(check_api=True)
        detail_lines = [
            f"{MARKER_OPT} Provider-слой: {'включён' if status.enabled else 'выключен'}",
            _line(
                _provider_detail_marker(status.enabled, status.configured),
                "Конфиг",
                "настроен" if status.configured else "не настроен",
            ),
            _line(
                _provider_detail_marker(status.enabled, status.reply_refine_available),
                "Reply refine",
                "доступен" if status.reply_refine_available else "недоступен",
            ),
            _line(
                _provider_detail_marker(status.enabled, status.digest_refine_available),
                "Digest refine",
                "доступен" if status.digest_refine_available else "недоступен",
            ),
            _line(
                MARKER_OK if status.enabled and status.available else MARKER_WARN if status.enabled else MARKER_OFF,
                "Причина",
                status.reason,
            ),
        ]
        return render_overview_card(
            title="Astra AFT / Provider",
            summary_lines=[
                f"Слой: {'включён' if status.enabled else 'выключен'}",
                f"API: {'доступен' if status.available else 'недоступен'}",
            ],
            detail_lines=detail_lines,
            next_step=_build_provider_next_step(status=status),
            rows=[[("Статус", screen_route(SCREEN_STATUS))]],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_PROVIDER,
        )

    async def _build_fullaccess_card(self) -> RenderedCard:
        status = await self.fullaccess_auth_service.build_status_report()
        detail_lines = [
            f"{MARKER_EXP} Только чтение, только вручную.",
            _line(MARKER_EXP if status.enabled else MARKER_OFF, "Слой", "включён" if status.enabled else "выключен"),
            _line(
                _fullaccess_detail_marker(status.enabled, status.authorized),
                "Авторизация",
                "авторизован" if status.authorized else "не авторизован",
            ),
            _line(
                _fullaccess_detail_marker(status.enabled, status.effective_readonly),
                "Read-only барьер",
                "активен" if status.effective_readonly else "не активен",
            ),
            _line(
                _fullaccess_detail_marker(status.enabled, status.session_exists),
                "Session",
                "есть" if status.session_exists else "нет",
            ),
            _line(
                MARKER_OK if status.synced_chat_count > 0 else MARKER_OFF if not status.enabled else MARKER_WARN,
                "Синкануто чатов",
                str(status.synced_chat_count),
            ),
            _line(
                _fullaccess_detail_marker(status.enabled, status.api_credentials_configured and status.phone_configured),
                "Конфиг",
                "настроен"
                if status.api_credentials_configured and status.phone_configured
                else "не настроен",
            ),
            f"{MARKER_WARN if status.enabled and not status.ready_for_manual_sync else MARKER_OFF if not status.enabled else MARKER_OK} Причина: {status.reason}",
        ]
        return render_overview_card(
            title="Astra AFT / Full-access",
            summary_lines=[
                f"Ручной sync: {_yes_no(status.ready_for_manual_sync)}",
                f"Синкануто сообщений: {status.synced_message_count}",
            ],
            detail_lines=detail_lines,
            next_step=_build_fullaccess_next_step(status),
            rows=[
                [("Чаты", fullaccess_chats_route()), ("Sync", fullaccess_chats_route())],
                [("Статус", screen_route(SCREEN_STATUS))],
            ],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_FULLACCESS,
        )

    async def _build_ops_card(self) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        recent_ops_label = _build_recent_ops_label(report)
        detail_lines = [
            _line(
                _ok_warn(facts.backup_tool_available),
                "Backup",
                "доступен" if facts.backup_tool_available else "недоступен",
            ),
            _line(
                _ok_warn(facts.export_tool_available),
                "Export",
                "доступен" if facts.export_tool_available else "недоступен",
            ),
            _line(
                _ok_warn(facts.last_backup_at is not None),
                "Последний backup",
                _format_timestamp(facts.last_backup_at),
            ),
            _line(
                _ok_warn(facts.last_export_at is not None),
                "Последний export",
                _format_timestamp(facts.last_export_at),
            ),
            f"{MARKER_OK if recent_ops_label == 'нет' else MARKER_WARN} Недавние предупреждения/ошибки: {recent_ops_label}",
            f"{MARKER_OK} CLI: python -m apps.ops status | python -m apps.ops backup | python -m apps.ops export",
        ]
        return render_overview_card(
            title="Astra AFT / Ops",
            summary_lines=[
                f"Backup доступен: {_yes_no(facts.backup_tool_available)}",
                f"Export доступен: {_yes_no(facts.export_tool_available)}",
            ],
            detail_lines=detail_lines,
            next_step=_build_ops_next_step(facts),
            rows=[[("Doctor", screen_route(SCREEN_DOCTOR)), ("Статус", screen_route(SCREEN_STATUS))]],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_OPS,
        )

    async def _build_reply_picker_card(self) -> RenderedCard:
        report = await self._build_report()
        ready_chats = await self.message_repository.list_reply_ready_chats(limit=6)
        message_counts = await self.message_repository.count_messages_by_chat()
        detail_lines: list[str] = []
        rows: list[list[tuple[str, str]]] = []
        for index, chat in enumerate(ready_chats, start=1):
            reference = _chat_route_reference(chat)
            detail_lines.append(
                f"{MARKER_OK} {index}. {chat.title}: {message_counts.get(chat.id, 0)} сообщ., {_chat_display_reference(chat)}"
            )
            rows.append([(_picker_button_label(chat.title), reply_chat_route(reference))])
        if not detail_lines:
            detail_lines.extend(_build_reply_picker_empty_state(report))
        return render_overview_card(
            title="Astra AFT / Reply / Выбор чата",
            summary_lines=[
                f"Готовых чатов для reply: {len(ready_chats)}",
                f"Few-shot: {_yes_no(report.facts.reply_examples > 0)}",
            ],
            detail_lines=detail_lines,
            next_step=(
                "Выбери чат, чтобы показать вариант ответа."
                if ready_chats
                else _build_reply_next_step(report)
            ),
            rows=rows,
            back_screen=SCREEN_REPLY,
            current_screen=SCREEN_REPLY_PICK,
        )

    async def _build_memory_picker_card(self) -> RenderedCard:
        report = await self._build_report()
        memory_cards = await self.chat_memory_repository.list_chat_memory(limit=6)
        detail_lines: list[str] = []
        rows: list[list[tuple[str, str]]] = []
        for index, memory in enumerate(memory_cards, start=1):
            chat = memory.chat
            if chat is None:
                continue
            reference = _chat_route_reference(chat)
            detail_lines.append(
                f"{MARKER_OK} {index}. {chat.title}: {memory.chat_summary_short or 'без краткой сводки'}"
            )
            rows.append([(_picker_button_label(chat.title), memory_chat_route(reference))])
        if not detail_lines:
            detail_lines.extend(_build_memory_picker_empty_state(report))
        return render_overview_card(
            title="Astra AFT / Memory / Выбор чата",
            summary_lines=[
                f"Карты чатов: {report.facts.chat_memory_cards}",
                f"Карты людей: {report.facts.person_memory_cards}",
            ],
            detail_lines=detail_lines,
            next_step=(
                "Выбери чат с готовой memory-карточкой."
                if rows
                else _build_memory_next_step(report)
            ),
            rows=rows,
            back_screen=SCREEN_MEMORY,
            current_screen=SCREEN_MEMORY_PICK,
        )

    async def _build_fullaccess_chats_card(self) -> RenderedCard:
        status = await self.fullaccess_auth_service.build_status_report()
        detail_lines: list[str] = []
        rows: list[list[tuple[str, str]]] = []
        error_message: str | None = None
        if status.ready_for_manual_sync:
            try:
                chat_list = await self._build_fullaccess_sync_service().list_chats(limit=6)
            except ValueError as error:
                chat_list = None
                error_message = str(error)
            else:
                for index, chat in enumerate(chat_list.chats, start=1):
                    detail_lines.append(
                        f"{MARKER_OK} {index}. {chat.title}: {chat.reference} ({chat.chat_type})"
                    )
                    rows.append(
                        [
                            (
                                _picker_button_label(chat.title),
                                fullaccess_chat_route(_fullaccess_chat_route_reference(chat.reference)),
                            )
                        ]
                    )
                if chat_list.truncated:
                    detail_lines.append(f"{MARKER_WARN} Список урезан до нескольких чатов для безопасного ручного sync.")
        if not detail_lines:
            detail_lines.extend(
                state_shell_lines(
                    marker=MARKER_WARN if status.enabled else MARKER_OFF,
                    status="Чаты недоступны",
                    meaning=error_message or status.reason,
                    next_step=_build_fullaccess_next_step(status),
                )
            )
        return render_overview_card(
            title="Astra AFT / Full-access / Чаты",
            summary_lines=[
                f"Готов к sync: {_yes_no(status.ready_for_manual_sync)}",
                f"Показано чатов: {len(rows)}",
            ],
            detail_lines=detail_lines,
            next_step=(
                "Выбери чат и запусти ручной sync."
                if rows
                else _build_fullaccess_next_step(status)
            ),
            rows=rows,
            back_screen=SCREEN_FULLACCESS,
            current_screen=SCREEN_FULLACCESS_CHATS,
        )

    async def build_reply_result_card(self, *, reference: str) -> RenderedCard:
        result = await self._build_reply_service().build_reply(reference)
        callback_reference = _route_reference(result.chat_reference or reference)
        title = f"Astra AFT / Reply / {result.chat_title or (result.chat_reference or reference)}"
        return render_text_card(
            title=title,
            lines=ReplyFormatter().format_inline_result(result).splitlines(),
            rows=[
                [
                    ("Похожие", reply_examples_route(callback_reference)),
                    ("Style", style_status_route(callback_reference)),
                ],
            ],
            back_screen=SCREEN_REPLY_PICK,
            current_screen=SCREEN_REPLY_PICK,
        )

    async def build_memory_result_card(self, *, reference: str) -> RenderedCard:
        return render_text_card(
            title="Astra AFT / Memory / Карточка",
            lines=(await self.memory_service.build_chat_memory_card(reference)).splitlines(),
            rows=[],
            back_screen=SCREEN_MEMORY_PICK,
            current_screen=SCREEN_MEMORY_PICK,
        )

    async def build_reply_examples_card(self, *, reference: str) -> RenderedCard:
        formatter = ReplyExamplesFormatter()
        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            lines = ["Источник не найден. Проверь chat_id или @username."]
        else:
            context_or_issue = await self._build_reply_context_builder().build(chat)
            if isinstance(context_or_issue, ReplyContextIssue):
                lines = [context_or_issue.message]
            else:
                retrieval = await ReplyExamplesRetriever(
                    reply_example_repository=self.reply_example_repository
                ).retrieve_for_context(
                    context_or_issue,
                    limit=5,
                )
                lines = formatter.format_matches(
                    chat_title=chat.title,
                    chat_reference=_chat_display_reference(chat),
                    retrieval_result=retrieval,
                ).splitlines()
        return render_text_card(
            title="Astra AFT / Reply / Похожие ответы",
            lines=lines,
            rows=[],
            back_screen=SCREEN_REPLY_PICK,
            current_screen=SCREEN_REPLY_PICK,
        )

    async def build_style_status_card(self, *, reference: str) -> RenderedCard:
        formatter = StyleFormatter()
        try:
            report = await self._build_style_service().build_style_status(reference)
            lines = formatter.format_status(report).splitlines()
        except ValueError as error:
            lines = [str(error)]
        return render_text_card(
            title="Astra AFT / Reply / Style",
            lines=lines,
            rows=[],
            back_screen=SCREEN_REPLY_PICK,
            current_screen=SCREEN_REPLY_PICK,
        )

    async def build_reminders_scan_result_card(
        self,
        *,
        window_argument: str,
        result: ReminderScanResult,
    ) -> RenderedCard:
        report = await self._build_report()
        facts = report.facts
        has_new_cards = result.created_count > 0
        lines = state_shell_lines(
            marker=MARKER_OK if has_new_cards else MARKER_WARN,
            status="Скан завершён",
            meaning=(
                "Ниже отправлены новые карточки для подтверждения."
                if has_new_cards
                else "В выбранном окне новых кандидатов не найдено."
            ),
            next_step="Подтверди нужные карточки." if has_new_cards else "Попробуй окно 24h или подожди новых сообщений.",
        )
        lines.extend(
            [
                "",
                "Детали",
                f"{MARKER_OK} Окно: {window_argument}",
                f"{MARKER_OK if result.created_count > 0 else MARKER_OFF} Новых карточек: {result.created_count}",
                f"{MARKER_OFF if result.skipped_existing_count == 0 else MARKER_OK} Уже известных пропущено: {result.skipped_existing_count}",
                f"{MARKER_OK if facts.owner_chat_id is not None else MARKER_WARN} Owner chat: {_yes_no(facts.owner_chat_id is not None)}",
                f"{MARKER_OK if facts.active_reminders > 0 else MARKER_OFF} Активных напоминаний: {facts.active_reminders}",
            ]
        )
        return render_text_card(
            title="Astra AFT / Reminders / Скан",
            lines=lines,
            rows=[
                [("Скан 24h", reminders_scan_route("24h")), ("Скан 12h", reminders_scan_route("12h"))],
                [("Напоминания", reminders_list_route())],
            ],
            back_screen=SCREEN_REMINDERS,
            current_screen=SCREEN_REMINDERS,
        )

    async def toggle_source(self, *, reference: str) -> RenderedCard:
        chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        if chat is None:
            lines = ["Источник не найден. Проверь chat_id или @username."]
        else:
            result = await SourceRegistryService(repository=self.chat_repository).set_source_enabled(
                reference,
                is_enabled=not chat.is_enabled,
            )
            lines = (
                result.to_user_message().splitlines()
                if result is not None
                else ["Источник не найден. Проверь chat_id или @username."]
            )
        return render_text_card(
            title="Astra AFT / Sources / Обновление",
            lines=lines,
            rows=[],
            back_screen=SCREEN_SOURCES,
            current_screen=SCREEN_SOURCES,
        )

    async def sync_fullaccess_chat(self, *, reference: str) -> RenderedCard:
        formatter = FullAccessFormatter()
        title = "Astra AFT / Full-access / Sync"
        try:
            result = await self._build_fullaccess_sync_service().sync_chat(reference)
            lines = _body_lines(formatter.format_sync_result(result), title=title)
        except ValueError as error:
            lines = state_shell_lines(
                marker=MARKER_WARN,
                status="Sync не запущен",
                meaning=str(error),
                next_step="/fullaccess_status",
            )
        return render_text_card(
            title=title,
            lines=lines,
            rows=[],
            back_screen=SCREEN_FULLACCESS_CHATS,
            current_screen=SCREEN_FULLACCESS_CHATS,
        )

    async def _build_report(self) -> OperationalReport:
        return await self.status_service._build_operational_report()

    def _build_digest_service(self) -> DigestEngineService:
        provider_manager = ProviderManager.from_settings(Settings())
        if isinstance(provider_manager, ProviderManager):
            provider_manager.setting_repository = self.status_service.setting_repository
        return DigestEngineService(
            message_repository=self.message_repository,
            digest_repository=self.digest_repository,
            setting_repository=self.status_service.setting_repository,
            builder=DigestBuilder(),
            formatter=DigestFormatter(),
            digest_refiner=DigestLLMRefiner(provider_manager=provider_manager),
        )

    async def _get_provider_status(self, *, check_api: bool):
        manager = self.status_service.provider_manager or ProviderManager.from_settings(Settings())
        if isinstance(manager, ProviderManager):
            manager.setting_repository = self.setting_repository
        return await manager.get_status(check_api=check_api)

    def _build_fullaccess_sync_service(self) -> FullAccessSyncService:
        return FullAccessSyncService(
            settings=Settings(),
            chat_repository=self.chat_repository,
            message_repository=self.message_repository,
            setting_repository=self.setting_repository,
        )

    def _build_reply_context_builder(self) -> ReplyContextBuilder:
        return ReplyContextBuilder(
            message_repository=self.message_repository,
            chat_memory_repository=self.chat_memory_repository,
            person_memory_repository=self.person_memory_repository,
        )

    def _build_reply_service(self) -> ReplyEngineService:
        provider_manager = ProviderManager.from_settings(Settings())
        if isinstance(provider_manager, ProviderManager):
            provider_manager.setting_repository = self.setting_repository
        return ReplyEngineService(
            chat_repository=self.chat_repository,
            message_repository=self.message_repository,
            chat_memory_repository=self.chat_memory_repository,
            person_memory_repository=self.person_memory_repository,
            context_builder=self._build_reply_context_builder(),
            classifier=ReplyClassifier(),
            strategy_resolver=ReplyStrategyResolver(),
            style_selector=StyleSelectorService(
                style_profile_repository=self.style_profile_repository,
                chat_style_override_repository=self.chat_style_override_repository,
                chat_memory_repository=self.chat_memory_repository,
                person_memory_repository=self.person_memory_repository,
            ),
            style_adapter=StyleAdapter(),
            persona_core_service=PersonaCoreService(self.setting_repository),
            persona_adapter=PersonaAdapter(),
            persona_guardrails=PersonaGuardrails(),
            reply_examples_retriever=ReplyExamplesRetriever(
                reply_example_repository=self.reply_example_repository
            ),
            reply_refiner=ReplyLLMRefiner(provider_manager=provider_manager),
            setting_repository=self.setting_repository,
        )

    def _build_style_service(self) -> StyleProfileService:
        return StyleProfileService(
            chat_repository=self.chat_repository,
            style_profile_repository=self.style_profile_repository,
            chat_style_override_repository=self.chat_style_override_repository,
            selector=StyleSelectorService(
                style_profile_repository=self.style_profile_repository,
                chat_style_override_repository=self.chat_style_override_repository,
                chat_memory_repository=self.chat_memory_repository,
                person_memory_repository=self.person_memory_repository,
            ),
        )


def _compose_checklist_line(*, index: int, item: OperationalCheck) -> str:
    marker = _check_marker(item)
    short_detail = item.detail.rstrip(".")
    return f"{index}. {marker} {_check_title(item)}: {short_detail}"


def _line(marker: str, label: str, detail: str) -> str:
    return format_status_line(marker, label, detail)


def _compose_reminders_line(report: OperationalReport) -> str:
    facts = report.facts
    marker = MARKER_OK if _find_check(report.layers, "reminders").ready else MARKER_WARN
    owner_label = facts.owner_chat_id if facts.owner_chat_id is not None else "не задан"
    return f"{marker} Напоминания: личный чат владельца {owner_label}, активных {facts.active_reminders}"


def _compose_provider_line(report: OperationalReport) -> str:
    status = report.facts.provider_status
    if not status.enabled:
        return f"{MARKER_OFF} Провайдер: выключен, базовый детерминированный режим активен."
    if status.configured and status.available:
        provider_name = status.provider_name or "провайдер"
        return f"{MARKER_OK} Провайдер: {provider_name} доступен."
    return f"{MARKER_WARN} Провайдер: {status.reason}"


def _compose_provider_digest_line(report: OperationalReport) -> str:
    status = report.facts.provider_status
    if not status.enabled:
        return f"{MARKER_OFF} LLM-улучшение выключено, базовый дайджест остаётся рабочим."
    marker = MARKER_OK if status.digest_refine_available else MARKER_WARN
    detail = "LLM-улучшение для дайджеста доступно." if status.digest_refine_available else status.reason
    return f"{marker} {detail}"


def _compose_provider_reply_line(report: OperationalReport) -> str:
    status = report.facts.provider_status
    if not status.enabled:
        return f"{MARKER_OFF} LLM-улучшение выключено, базовый слой ответов остаётся рабочим."
    marker = MARKER_OK if status.reply_refine_available else MARKER_WARN
    detail = "LLM-улучшение для ответов доступно." if status.reply_refine_available else status.reason
    return f"{marker} {detail}"


def _compose_fullaccess_line(report: OperationalReport) -> str:
    status = report.facts.fullaccess_status
    if status is None or not status.enabled:
        return f"{MARKER_OFF} Full-access: выключен."
    if status.ready_for_manual_sync:
        return (
            f"{MARKER_EXP} Full-access: готов, синхронизировано чатов {status.synced_chat_count}, "
            f"сообщений {status.synced_message_count}."
        )
    return f"{MARKER_WARN} Full-access: {status.reason}"


def _compose_ops_line(facts) -> str:
    backup_label = "доступно" if facts.backup_tool_available else "недоступно"
    export_label = "доступен" if facts.export_tool_available else "недоступен"
    errors = [
        label
        for label, value in (
            ("worker", facts.recent_worker_error),
            ("provider", facts.recent_provider_error),
            ("full-access", facts.recent_fullaccess_error),
        )
        if value
    ]
    error_label = ", ".join(errors) if errors else "нет"
    return (
        f"{MARKER_OK} Операционный слой: резервное копирование "
        f"{backup_label}, экспорт {export_label}, недавние ошибки: {error_label}"
    )


def _compose_persona_line(facts) -> str:
    state = facts.persona_state
    if state.enabled and state.core_loaded and state.guardrails_active:
        return f"{MARKER_OK} Персона: ядро загружено, защитные правила активны."
    return f"{MARKER_WARN} Персона: ядро или защитные правила ещё не готовы."


def _ok_warn(value: bool) -> str:
    return ready_marker(value)


def _build_next_step(report: OperationalReport) -> str:
    next_command = report.next_command
    if next_command == "/start":
        return "/start в личном чате"
    if next_command == "/source_add":
        return "/source_add <chat_id|@username>"
    if next_command == "/sources":
        return "Накопить сообщения или использовать /fullaccess_sync"
    if next_command == "/digest_target":
        return "/digest_target <chat_id|@username>"
    if next_command == "/memory_rebuild":
        return "/memory_rebuild"
    if next_command == "/reply":
        return "/reply <chat_id|@username>"
    if next_command == "/reminders_scan":
        return "/reminders_scan 24h"
    if next_command == "/provider_status":
        return "/provider_status"
    if next_command == "/fullaccess_status":
        return "/fullaccess_status"
    if report.next_steps:
        return report.next_steps[0]
    return "Core-путь готов. Можно использовать /digest_now, /reply и /reminders_scan."


def _build_navigation_button(report: OperationalReport) -> tuple[str, str] | None:
    next_command = report.next_command
    mapping = {
        "/source_add": ("Источники", screen_route(SCREEN_SOURCES)),
        "/sources": ("Источники", screen_route(SCREEN_SOURCES)),
        "/digest_target": ("Дайджест", screen_route(SCREEN_DIGEST)),
        "/memory_rebuild": ("Память", screen_route(SCREEN_MEMORY)),
        "/reply": ("Ответы", screen_route(SCREEN_REPLY)),
        "/reminders_scan": ("Напоминания", screen_route(SCREEN_REMINDERS)),
        "/provider_status": ("Provider", screen_route(SCREEN_PROVIDER)),
        "/fullaccess_status": ("Full-access", screen_route(SCREEN_FULLACCESS)),
    }
    return mapping.get(next_command)


def _build_sources_next_step(report: OperationalReport) -> str:
    if report.facts.active_sources == 0:
        return "/source_add <chat_id|@username>"
    if not report.facts.has_messages:
        return "Накопить сообщения или использовать /fullaccess_sync"
    return "Открой Digest или настрой /digest_target"


def _build_digest_next_step(report: OperationalReport) -> str:
    if not report.facts.digest_target_configured:
        return "/digest_target <chat_id|@username>"
    if not report.facts.has_messages:
        return "Сначала нужны сообщения в локальной БД"
    return "/digest_now 24h или кнопка «Собрать 24h»"


def _build_memory_next_step(report: OperationalReport) -> str:
    if not report.facts.has_messages:
        return "Сначала накопи сообщения через Источники"
    if not report.facts.has_memory_cards:
        return "/memory_rebuild"
    return "Открой «Чаты» в Memory и выбери готовую карточку."


def _build_reply_next_step(report: OperationalReport) -> str:
    if not report.facts.has_messages:
        return "Сначала накопи сообщения через Источники"
    if not report.facts.has_memory_cards:
        return "/memory_rebuild"
    if report.facts.reply_ready_chats > 0:
        return "Открой «Выбрать чат» в Reply."
    return "Подходящих reply-ready чатов пока нет."


def _build_reminders_next_step(report: OperationalReport) -> str:
    if report.facts.owner_chat_id is None:
        return "/start в личном чате"
    if not report.facts.has_messages:
        return "Сначала нужны сообщения для /reminders_scan"
    return "/reminders_scan 24h"


def _build_provider_next_step(*, status) -> str:
    if not status.enabled:
        return "Core-путь работает и без provider."
    if not status.configured:
        return "Проверь /provider_status и env-конфиг."
    if not status.available:
        return "Проверь доступность API через /provider_status."
    return "Provider готов; можно использовать Digest и Reply."


def _build_fullaccess_next_step(status) -> str:
    if not status.enabled:
        return "Core-путь работает и без experimental слоя."
    if not status.authorized:
        return "/fullaccess_status или /fullaccess_login"
    if status.ready_for_manual_sync:
        return "Открой список чатов и выбери manual sync."
    return "/fullaccess_status"


def _build_ops_next_step(facts) -> str:
    if facts.last_backup_at is None:
        return "python -m apps.ops backup"
    if facts.last_export_at is None:
        return "python -m apps.ops export"
    return "python -m apps.ops status"


def _build_recent_ops_label(report: OperationalReport) -> str:
    facts = report.facts
    values = [
        facts.recent_worker_error,
        facts.recent_provider_error,
        facts.recent_fullaccess_error,
        *report.warnings[:2],
    ]
    compact = [_compact_label(value, limit=54) for value in values if value]
    if not compact:
        return "нет"
    return " | ".join(compact[:3])


def _build_reply_picker_empty_state(report: OperationalReport) -> list[str]:
    if not report.facts.has_messages:
        return state_shell_lines(
            marker=MARKER_WARN,
            status="Нет данных для Reply",
            meaning="В локальной БД ещё нет сообщений, из которых можно собрать контекст.",
            next_step="Добавь источник и дождись ingest-сообщений.",
        )
    if not report.facts.has_memory_cards:
        return state_shell_lines(
            marker=MARKER_WARN,
            status="Memory ещё не собрана",
            meaning="Reply нужен локальный контекст по чатам и людям.",
            next_step="/memory_rebuild",
        )
    return state_shell_lines(
        marker=MARKER_OFF,
        status="Reply-ready чатов пока нет",
        meaning="Сообщения есть, но подходящего чата с достаточным контекстом пока не найдено.",
        next_step="Подожди новых сообщений или открой Memory.",
    )


def _build_memory_picker_empty_state(report: OperationalReport) -> list[str]:
    if not report.facts.has_messages:
        return state_shell_lines(
            marker=MARKER_WARN,
            status="Нет данных для Memory",
            meaning="Memory строится только из сообщений, сохранённых в локальной БД.",
            next_step="Сначала накопи сообщения через источники.",
        )
    return state_shell_lines(
        marker=MARKER_WARN,
        status="Карточки Memory ещё не построены",
        meaning="Сообщения уже есть, но rebuild ещё не запускался.",
        next_step="/memory_rebuild",
    )


def _check_marker(item: OperationalCheck) -> str:
    if item.key == "provider_layer":
        return MARKER_OPT if item.ready else MARKER_WARN
    if item.key == "fullaccess_layer":
        if item.ready and "выключен" in item.detail.lower():
            return MARKER_OFF
        return MARKER_EXP if item.ready else MARKER_WARN
    return MARKER_OK if item.ready else MARKER_WARN


def _check_title(item: OperationalCheck) -> str:
    titles = {
        "owner_chat": "Личный чат",
        "active_source": "Источник",
        "messages": "Сообщения",
        "digest_target": "Digest target",
        "memory_layer": "Memory",
        "reply_layer": "Reply",
        "reminders_layer": "Reminders",
        "provider_layer": "Provider",
        "fullaccess_layer": "Full-access",
    }
    return titles.get(item.key, item.title)


def _provider_detail_marker(enabled: bool, ready: bool) -> str:
    if ready:
        return MARKER_OK
    return MARKER_WARN if enabled else MARKER_OFF


def _fullaccess_detail_marker(enabled: bool, ready: bool) -> str:
    if ready:
        return MARKER_OK
    return MARKER_WARN if enabled else MARKER_OFF


def _doctor_warning_marker(value: str) -> str:
    return MARKER_OK if "критичных проблем не найдено" in value.lower() else MARKER_WARN


def _chat_route_reference(chat) -> str:
    handle = getattr(chat, "handle", None)
    if isinstance(handle, str) and handle.strip():
        return handle.strip().lstrip("@")
    return str(chat.telegram_chat_id)


def _chat_display_reference(chat) -> str:
    handle = getattr(chat, "handle", None)
    if isinstance(handle, str) and handle.strip():
        return f"@{handle.strip().lstrip('@')}"
    return str(chat.telegram_chat_id)


def _route_reference(reference: str) -> str:
    return reference.strip().lstrip("@")


def _fullaccess_chat_route_reference(reference: str) -> str:
    return reference.strip().lstrip("@")


def _picker_button_label(value: str, *, limit: int = 28) -> str:
    normalized = " ".join(value.split()).strip() or "Без названия"
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _source_toggle_button_label(chat) -> str:
    action = "Выключить" if chat.is_enabled else "Включить"
    return _picker_button_label(f"{action} {chat.title}", limit=32)


def _compact_label(value: str, *, limit: int = 54) -> str:
    normalized = " ".join(value.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _body_lines(text: str, *, title: str) -> list[str]:
    lines = text.splitlines()
    if lines[:2] == [title, ""]:
        return lines[2:]
    if lines[:1] == [title]:
        return lines[1:]
    return lines


def _find_check(items: tuple[OperationalCheck, ...], key: str) -> OperationalCheck:
    for item in items:
        if item.key == key:
            return item
    raise KeyError(key)


def _first_unready_title(report: OperationalReport) -> str:
    for item in report.checklist:
        if not item.ready:
            return item.title
    return "всё готово"


def _core_path_ready(report: OperationalReport) -> bool:
    return all(
        item.ready
        for item in report.checklist
        if item.key
        not in {
            "provider_layer",
            "fullaccess_layer",
        }
    )


def _is_cold_start(report: OperationalReport) -> bool:
    facts = report.facts
    return (
        facts.total_sources == 0
        and facts.total_messages == 0
        and not facts.digest_target_configured
        and not facts.has_memory_cards
        and facts.reply_examples == 0
        and facts.active_reminders == 0
        and facts.confirmed_tasks == 0
        and facts.candidate_tasks == 0
    )


def _yes_no(value: bool) -> str:
    return "да" if value else "нет"


def _format_timestamp(value: datetime | str | None) -> str:
    if value is None:
        return "ещё нет"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M UTC")
