from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.chat_memory_builder import ChatMemoryBuilder
from services.digest_builder import DigestBuilder
from services.digest_engine import DigestEngineService, DigestPublisherService, MessageSenderProtocol
from services.digest_formatter import DigestFormatter
from services.inline_navigation import (
    SCREEN_CHECKLIST,
    SCREEN_DIGEST,
    SCREEN_DOCTOR,
    SCREEN_HOME,
    SCREEN_MEMORY,
    SCREEN_REMINDERS,
    SCREEN_REPLY,
    SCREEN_REPLY_HELP,
    SCREEN_SOURCES,
    SCREEN_SOURCES_HELP,
    SCREEN_STATUS,
    digest_run_route,
    memory_rebuild_route,
    reminders_list_route,
    reminders_scan_route,
    reminders_tasks_route,
    reply_help_route,
    screen_route,
    sources_help_route,
)
from services.memory_builder import MemoryRebuildResult, MemoryService
from services.memory_formatter import MemoryFormatter
from services.people_memory_builder import PeopleMemoryBuilder
from services.providers.digest_refiner import DigestLLMRefiner
from services.providers.manager import ProviderManager
from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter
from services.reminder_models import ReminderScanResult
from services.reminder_service import ReminderService
from services.render_cards import RenderedCard, render_help_card, render_home_card, render_overview_card
from services.status_summary import BotStatusService
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
    memory_service: MemoryService
    reminder_service: ReminderService

    @classmethod
    def from_session(cls, session: AsyncSession) -> "SetupUIService":
        settings = Settings()
        message_repository = MessageRepository(session)
        setting_repository = SettingRepository(session)
        provider_manager = ProviderManager.from_settings(settings)
        if isinstance(provider_manager, ProviderManager):
            provider_manager.setting_repository = setting_repository

        digest_repository = DigestRepository(session)
        return cls(
            status_service=BotStatusService(
                settings=settings,
                chat_repository=ChatRepository(session),
                setting_repository=setting_repository,
                system_repository=SystemRepository(session),
                message_repository=message_repository,
                digest_repository=digest_repository,
                chat_memory_repository=ChatMemoryRepository(session),
                person_memory_repository=PersonMemoryRepository(session),
                style_profile_repository=StyleProfileRepository(session),
                chat_style_override_repository=ChatStyleOverrideRepository(session),
                task_repository=TaskRepository(session),
                reminder_repository=ReminderRepository(session),
                reply_example_repository=ReplyExampleRepository(session),
                provider_manager=provider_manager,
                fullaccess_auth_service=FullAccessAuthService(
                    settings=settings,
                    setting_repository=setting_repository,
                    message_repository=message_repository,
                ),
            ),
            chat_repository=ChatRepository(session),
            message_repository=message_repository,
            digest_repository=digest_repository,
            memory_service=MemoryService(
                chat_repository=ChatRepository(session),
                message_repository=message_repository,
                digest_repository=digest_repository,
                setting_repository=setting_repository,
                chat_memory_repository=ChatMemoryRepository(session),
                person_memory_repository=PersonMemoryRepository(session),
                chat_builder=ChatMemoryBuilder(),
                people_builder=PeopleMemoryBuilder(),
                formatter=MemoryFormatter(),
            ),
            reminder_service=ReminderService(
                chat_repository=ChatRepository(session),
                message_repository=message_repository,
                chat_memory_repository=ChatMemoryRepository(session),
                setting_repository=setting_repository,
                task_repository=TaskRepository(session),
                reminder_repository=ReminderRepository(session),
                extractor=ReminderExtractor(),
                formatter=ReminderFormatter(),
            ),
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
        if screen == SCREEN_REPLY:
            return await self._build_reply_card()
        if screen == SCREEN_REPLY_HELP:
            return self._build_reply_help_card()
        if screen == SCREEN_REMINDERS:
            return await self._build_reminders_card()
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
    ) -> str | None:
        plan = await self._build_digest_service().build_manual_digest(window_argument)
        publish_result = await DigestPublisherService(self.digest_repository).publish(
            plan=plan,
            preview_chat_id=preview_chat_id,
            sender=sender,
        )
        return publish_result.notice

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
            title="Astra AFT / Центр управления",
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
        rows = [[("Checklist", screen_route(SCREEN_CHECKLIST)), ("Doctor", screen_route(SCREEN_DOCTOR))]]
        rows = [[("Чеклист", screen_route(SCREEN_CHECKLIST)), ("Диагностика", screen_route(SCREEN_DOCTOR))]]
        navigation_button = _build_navigation_button(report)
        if navigation_button is not None:
            rows.append([navigation_button])
        return render_overview_card(
            title="Astra AFT / Статус",
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
        detail_lines = [_compose_checklist_line(item) for item in report.checklist]
        rows = [[("Статус", screen_route(SCREEN_STATUS)), ("Диагностика", screen_route(SCREEN_DOCTOR))]]
        navigation_button = _build_navigation_button(report)
        if navigation_button is not None:
            rows.append([navigation_button])
        return render_overview_card(
            title="Astra AFT / Чеклист",
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
            *[f"[OK] {item}" for item in doctor.ok_items[:2]],
            *[f"[WARN] {item}" for item in doctor.warnings[:3]],
        ]
        hidden_warning_count = max(len(doctor.warnings) - 3, 0)
        if hidden_warning_count:
            detail_lines.append(f"[WARN] Ещё предупреждений: {hidden_warning_count}")
        detail_lines.append(_compose_ops_line(report.facts))
        rows = [[("Статус", screen_route(SCREEN_STATUS)), ("Чеклист", screen_route(SCREEN_CHECKLIST))]]
        return render_overview_card(
            title="Astra AFT / Диагностика",
            summary_lines=[
                f"ОК-пунктов: {len(doctor.ok_items)}",
                f"Предупреждений: {len(doctor.warnings)}",
            ],
            detail_lines=detail_lines,
            next_step=doctor.next_steps[0] if doctor.next_steps else _build_next_step(report),
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
            marker = "[OK]" if chat.is_enabled and message_counts.get(chat.id, 0) > 0 else "[OFF]" if not chat.is_enabled else "[WARN]"
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
            detail_lines.append("[WARN] Источники пока не добавлены.")
        if len(chats) > 4:
            detail_lines.append(f"[OK] Ещё источников: {len(chats) - 4}")

        return render_overview_card(
            title="Astra AFT / Источники",
            summary_lines=[
                f"Всего источников: {report.facts.total_sources}",
                f"Активных: {report.facts.active_sources}",
                f"С данными: {report.facts.chats_with_data}",
            ],
            detail_lines=detail_lines,
            next_step=_build_sources_next_step(report),
            rows=[[("Как добавить", sources_help_route())]],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_SOURCES,
        )

    def _build_sources_help_card(self) -> RenderedCard:
        return render_help_card(
            title="Astra AFT / Источники / Как добавить",
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
            "[OK] Digest читает локальную БД и публикует preview в текущий чат.",
        ]
        return render_overview_card(
            title="Astra AFT / Дайджест",
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
            _line(_ok_warn(facts.person_memory_cards > 0), "Карты людей", str(facts.person_memory_cards)),
            _line(_ok_warn(facts.last_memory_rebuild_at is not None), "Последний rebuild", _format_timestamp(facts.last_memory_rebuild_at)),
            "[OK] Память строится только по локальной SQLite-БД.",
        ]
        return render_overview_card(
            title="Astra AFT / Память",
            summary_lines=[
                f"Карт чатов: {facts.chat_memory_cards}",
                f"Карт людей: {facts.person_memory_cards}",
            ],
            detail_lines=detail_lines,
            next_step=_build_memory_next_step(report),
            rows=[[("Пересобрать", memory_rebuild_route())]],
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
            title="Astra AFT / Ответы",
            summary_lines=[
                f"Готовых чатов: {facts.reply_ready_chats}",
                f"Похожие ответы: {_yes_no(facts.reply_examples > 0)}",
            ],
            detail_lines=detail_lines,
            next_step=_build_reply_next_step(report),
            rows=[[("Как использовать", reply_help_route())]],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_REPLY,
        )

    def _build_reply_help_card(self) -> RenderedCard:
        return render_help_card(
            title="Astra AFT / Ответы / Как использовать",
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
            _line(_ok_warn(facts.candidate_tasks > 0), "Кандидаты", str(facts.candidate_tasks)),
            _line(_ok_warn(facts.confirmed_tasks > 0), "Активные задачи", str(facts.confirmed_tasks)),
            _line(_ok_warn(facts.active_reminders > 0), "Активные напоминания", str(facts.active_reminders)),
            _line(_ok_warn(facts.reminders_worker_ready), "Фоновая доставка", _yes_no(facts.reminders_worker_ready)),
            _line(
                _ok_warn(facts.last_reminder_notification is not None),
                "Последняя доставка",
                _format_timestamp(facts.last_reminder_notification),
            ),
        ]
        return render_overview_card(
            title="Astra AFT / Напоминания",
            summary_lines=[
                f"Кандидатов: {facts.candidate_tasks}",
                f"Активных напоминаний: {facts.active_reminders}",
            ],
            detail_lines=detail_lines,
            next_step=_build_reminders_next_step(report),
            rows=[
                [("Скан 24h", reminders_scan_route("24h"))],
                [("Задачи", reminders_tasks_route()), ("Напоминания", reminders_list_route())],
            ],
            back_screen=SCREEN_HOME,
            current_screen=SCREEN_REMINDERS,
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


def _compose_checklist_line(item: OperationalCheck) -> str:
    marker = "[OK]" if item.ready else "[WARN]"
    short_detail = item.detail.rstrip(".")
    return f"{marker} {item.title}: {short_detail}"


def _line(marker: str, label: str, detail: str) -> str:
    return f"{marker} {label}: {detail}"


def _compose_reminders_line(report: OperationalReport) -> str:
    facts = report.facts
    marker = "[OK]" if _find_check(report.layers, "reminders").ready else "[WARN]"
    owner_label = facts.owner_chat_id if facts.owner_chat_id is not None else "не задан"
    return f"{marker} Напоминания: личный чат владельца {owner_label}, активных {facts.active_reminders}"


def _compose_provider_line(report: OperationalReport) -> str:
    status = report.facts.provider_status
    if not status.enabled:
        return "[OFF] Провайдер: выключен, базовый детерминированный режим активен."
    if status.configured and status.available:
        provider_name = status.provider_name or "провайдер"
        return f"[OK] Провайдер: {provider_name} доступен."
    return f"[WARN] Провайдер: {status.reason}"


def _compose_provider_digest_line(report: OperationalReport) -> str:
    status = report.facts.provider_status
    if not status.enabled:
        return "[OFF] LLM-улучшение выключено, базовый дайджест остаётся рабочим."
    marker = "[OK]" if status.digest_refine_available else "[WARN]"
    detail = "LLM-улучшение для дайджеста доступно." if status.digest_refine_available else status.reason
    return f"{marker} {detail}"


def _compose_provider_reply_line(report: OperationalReport) -> str:
    status = report.facts.provider_status
    if not status.enabled:
        return "[OFF] LLM-улучшение выключено, базовый слой ответов остаётся рабочим."
    marker = "[OK]" if status.reply_refine_available else "[WARN]"
    detail = "LLM-улучшение для ответов доступно." if status.reply_refine_available else status.reason
    return f"{marker} {detail}"


def _compose_fullaccess_line(report: OperationalReport) -> str:
    status = report.facts.fullaccess_status
    if status is None or not status.enabled:
        return "[OFF] Full-access: выключен."
    if status.ready_for_manual_sync:
        return (
            f"[EXP] Full-access: готов, синхронизировано чатов {status.synced_chat_count}, "
            f"сообщений {status.synced_message_count}."
        )
    return f"[WARN] Full-access: {status.reason}"


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
        "[OK] Операционный слой: резервное копирование "
        f"{backup_label}, экспорт {export_label}, недавние ошибки: {error_label}"
    )


def _compose_persona_line(facts) -> str:
    state = facts.persona_state
    if state.enabled and state.core_loaded and state.guardrails_active:
        return "[OK] Персона: ядро загружено, защитные правила активны."
    return "[WARN] Персона: ядро или защитные правила ещё не готовы."


def _ok_warn(value: bool) -> str:
    return "[OK]" if value else "[WARN]"


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
    return "Открой Reply и используй /reply <chat_id|@username>"


def _build_reply_next_step(report: OperationalReport) -> str:
    if not report.facts.has_messages:
        return "Сначала накопи сообщения через Источники"
    if not report.facts.has_memory_cards:
        return "/memory_rebuild"
    return "/reply <chat_id|@username>"


def _build_reminders_next_step(report: OperationalReport) -> str:
    if report.facts.owner_chat_id is None:
        return "/start в личном чате"
    if not report.facts.has_messages:
        return "Сначала нужны сообщения для /reminders_scan"
    return "/reminders_scan 24h"


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
