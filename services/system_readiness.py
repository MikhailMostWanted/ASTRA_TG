from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.models import FullAccessStatusReport
from services.bot_owner import BotOwnerService
from services.digest_target import DigestTargetService
from services.operational_state import OperationalStateService
from services.digest_window import parse_digest_window
from services.persona_core import PersonaCoreService, PersonaState
from services.providers.manager import ProviderManager
from services.providers.models import ProviderStatus
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
from worker.jobs import list_registered_jobs


STYLE_READY_PROFILE_COUNT = 6


@dataclass(frozen=True, slots=True)
class OperationalFacts:
    schema_revision: str | None
    owner_chat_id: int | None
    total_sources: int
    active_sources: int
    digest_sources: int
    total_messages: int
    chats_with_data: int
    last_message_at: datetime | None
    reply_ready_chats: int
    total_digests: int
    last_digest_at: datetime | None
    digest_target_configured: bool
    digest_target_label: str | None
    digest_window_label: str
    digest_window_messages: int
    chat_memory_cards: int
    person_memory_cards: int
    last_memory_rebuild_at: datetime | str | None
    style_profiles: int
    style_overrides: int
    persona_state: PersonaState
    reply_examples: int
    reply_example_chats: int
    candidate_tasks: int
    confirmed_tasks: int
    active_reminders: int
    last_reminder_notification: datetime | None
    provider_status: ProviderStatus
    fullaccess_status: FullAccessStatusReport | None
    worker_jobs: tuple[str, ...]
    backup_tool_available: bool
    export_tool_available: bool
    last_backup_at: datetime | None
    last_backup_path: str | None
    last_export_at: datetime | None
    last_export_path: str | None
    last_fullaccess_sync_at: datetime | None
    recent_worker_error: str | None
    recent_provider_error: str | None
    recent_fullaccess_error: str | None
    startup_warnings: tuple[str, ...]

    @property
    def has_messages(self) -> bool:
        return self.total_messages > 0

    @property
    def has_memory_cards(self) -> bool:
        return self.chat_memory_cards > 0 or self.person_memory_cards > 0

    @property
    def style_ready(self) -> bool:
        return self.style_profiles >= STYLE_READY_PROFILE_COUNT

    @property
    def persona_ready(self) -> bool:
        return (
            self.persona_state.enabled
            and self.persona_state.core_loaded
            and self.persona_state.guardrails_active
        )

    @property
    def reminders_worker_ready(self) -> bool:
        return "reminder_delivery" in self.worker_jobs


@dataclass(frozen=True, slots=True)
class OperationalCheck:
    key: str
    title: str
    ready: bool
    detail: str
    next_command: str | None = None
    next_action: str | None = None


@dataclass(frozen=True, slots=True)
class OperationalReport:
    facts: OperationalFacts
    checklist: tuple[OperationalCheck, ...]
    layers: tuple[OperationalCheck, ...]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]

    @property
    def ready_check_count(self) -> int:
        return sum(1 for item in self.checklist if item.ready)

    @property
    def total_check_count(self) -> int:
        return len(self.checklist)

    @property
    def next_command(self) -> str | None:
        for item in self.checklist:
            if not item.ready and item.next_command:
                return item.next_command
        for item in self.layers:
            if not item.ready and item.next_command:
                return item.next_command
        return None


@dataclass(slots=True)
class SystemReadinessService:
    chat_repository: ChatRepository
    setting_repository: SettingRepository
    system_repository: SystemRepository
    message_repository: MessageRepository
    digest_repository: DigestRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    style_profile_repository: StyleProfileRepository
    chat_style_override_repository: ChatStyleOverrideRepository
    task_repository: TaskRepository | None = None
    reminder_repository: ReminderRepository | None = None
    reply_example_repository: ReplyExampleRepository | None = None
    provider_manager: ProviderManager | None = None
    fullaccess_auth_service: FullAccessAuthService | None = None
    settings: Settings | None = None

    async def build_report(self) -> OperationalReport:
        facts = await self._collect_facts()
        checklist = self._build_checklist(facts)
        layers = self._build_layers(facts)
        warnings = tuple(_dedupe(self._build_warnings(facts, checklist, layers)))
        next_steps = tuple(
            _dedupe(
                [
                    item.next_action
                    for item in (*checklist, *layers)
                    if not item.ready and item.next_action
                ]
            )
        )
        return OperationalReport(
            facts=facts,
            checklist=checklist,
            layers=layers,
            warnings=warnings,
            next_steps=next_steps,
        )

    async def _collect_facts(self) -> OperationalFacts:
        effective_settings = self.settings or Settings()
        state_service = OperationalStateService(self.setting_repository)
        total_sources = await self.chat_repository.count_chats()
        active_sources = await self.chat_repository.count_enabled_chats()
        digest_sources = await self.chat_repository.count_digest_enabled_chats()
        total_messages = await self.message_repository.count_messages()
        message_counts = await self.message_repository.count_messages_by_chat()
        last_message_at = await self.message_repository.get_last_message_timestamp()
        reply_ready_chats = await self.message_repository.count_chats_ready_for_reply()
        total_digests = await self.digest_repository.count_digests()
        last_digest = await self.digest_repository.get_last_digest()
        chat_memory_cards = await self.chat_memory_repository.count_chat_memory()
        person_memory_cards = await self.person_memory_repository.count_people_memory()
        style_profiles = await self.style_profile_repository.count_profiles()
        style_overrides = await self.chat_style_override_repository.count_overrides()
        reply_examples = (
            await self.reply_example_repository.count_examples()
            if self.reply_example_repository is not None
            else 0
        )
        reply_example_chats = (
            await self.reply_example_repository.count_chats_with_examples()
            if self.reply_example_repository is not None
            else 0
        )
        candidate_tasks = (
            await self.task_repository.count_candidates()
            if self.task_repository is not None
            else 0
        )
        confirmed_tasks = (
            await self.task_repository.count_confirmed()
            if self.task_repository is not None
            else 0
        )
        active_reminders = (
            await self.reminder_repository.count_active_reminders()
            if self.reminder_repository is not None
            else 0
        )
        last_reminder_notification = (
            await self.reminder_repository.get_last_notification_at()
            if self.reminder_repository is not None
            else None
        )
        persona_state = await PersonaCoreService(self.setting_repository).load_state()
        last_memory_rebuild_at = await self.setting_repository.get_value("memory.last_rebuild_at")
        if last_memory_rebuild_at is None:
            last_memory_rebuild_at = (
                await self.chat_memory_repository.get_last_updated_at()
                or await self.person_memory_repository.get_last_updated_at()
            )
        digest_target = await DigestTargetService(self.setting_repository).get_target()
        owner_chat_id = await BotOwnerService(self.setting_repository).get_owner_chat_id()
        schema_revision = await self.system_repository.get_schema_revision()
        provider_status = await self._get_provider_status()
        fullaccess_status = (
            await self.fullaccess_auth_service.build_status_report()
            if self.fullaccess_auth_service is not None
            else None
        )
        last_backup = await state_service.get_named_snapshot("backup")
        last_export = await state_service.get_named_snapshot("export")
        last_fullaccess_sync = await state_service.get_named_snapshot("fullaccess_sync")
        last_worker_error = await state_service.get_error("worker")
        last_provider_error = await state_service.get_error("provider")
        last_fullaccess_error = await state_service.get_error("fullaccess")
        bot_startup = await state_service.get_named_snapshot("bot_startup")
        worker_startup = await state_service.get_named_snapshot("worker_startup")
        digest_window = parse_digest_window(None)
        digest_window_counts = await self.message_repository.count_messages_by_digest_chat(
            window_start=digest_window.start,
            window_end=digest_window.end,
        )
        return OperationalFacts(
            schema_revision=schema_revision,
            owner_chat_id=owner_chat_id,
            total_sources=total_sources,
            active_sources=active_sources,
            digest_sources=digest_sources,
            total_messages=total_messages,
            chats_with_data=len(message_counts),
            last_message_at=last_message_at,
            reply_ready_chats=reply_ready_chats,
            total_digests=total_digests,
            last_digest_at=last_digest.created_at if last_digest is not None else None,
            digest_target_configured=digest_target.is_configured,
            digest_target_label=digest_target.label,
            digest_window_label=digest_window.label,
            digest_window_messages=sum(digest_window_counts.values()),
            chat_memory_cards=chat_memory_cards,
            person_memory_cards=person_memory_cards,
            last_memory_rebuild_at=last_memory_rebuild_at,
            style_profiles=style_profiles,
            style_overrides=style_overrides,
            persona_state=persona_state,
            reply_examples=reply_examples,
            reply_example_chats=reply_example_chats,
            candidate_tasks=candidate_tasks,
            confirmed_tasks=confirmed_tasks,
            active_reminders=active_reminders,
            last_reminder_notification=last_reminder_notification,
            provider_status=provider_status,
            fullaccess_status=fullaccess_status,
            worker_jobs=list_registered_jobs(),
            backup_tool_available=effective_settings.sqlite_database_path is not None,
            export_tool_available=True,
            last_backup_at=last_backup.timestamp if last_backup is not None else None,
            last_backup_path=_read_string(last_backup, "path"),
            last_export_at=last_export.timestamp if last_export is not None else None,
            last_export_path=_read_string(last_export, "path"),
            last_fullaccess_sync_at=(
                last_fullaccess_sync.timestamp if last_fullaccess_sync is not None else None
            ),
            recent_worker_error=last_worker_error.message if last_worker_error is not None else None,
            recent_provider_error=(
                last_provider_error.message if last_provider_error is not None else None
            ),
            recent_fullaccess_error=(
                last_fullaccess_error.message if last_fullaccess_error is not None else None
            ),
            startup_warnings=tuple(
                _dedupe(
                    [
                        *(_read_startup_warnings(bot_startup, prefix="bot") or []),
                        *(_read_startup_warnings(worker_startup, prefix="worker") or []),
                    ]
                )
            ),
        )

    def _build_checklist(self, facts: OperationalFacts) -> tuple[OperationalCheck, ...]:
        provider_ready, provider_detail = _provider_check(facts)
        fullaccess_ready, fullaccess_detail = _fullaccess_check(facts)
        reply_ready, reply_detail = _reply_check(facts)
        reminders_ready, reminders_detail = _reminders_check(facts)
        digest_target_label = facts.digest_target_label or "канал не задан"
        memory_detail = (
            f"Memory-карт: чатов {facts.chat_memory_cards}, людей {facts.person_memory_cards}."
            if facts.has_memory_cards
            else (
                "Сообщения уже есть, но memory cards ещё не строились."
                if facts.has_messages
                else "Сначала нужны сообщения, затем /memory_rebuild."
            )
        )
        return (
            OperationalCheck(
                key="owner_chat",
                title="owner chat",
                ready=facts.owner_chat_id is not None,
                detail=(
                    f"owner chat сохранён: {facts.owner_chat_id}."
                    if facts.owner_chat_id is not None
                    else "Бот ещё не знает личный чат владельца."
                ),
                next_command="/start",
                next_action="Открой личный чат с ботом и отправь /start, чтобы сохранить owner chat.",
            ),
            OperationalCheck(
                key="active_source",
                title="активный источник",
                ready=facts.active_sources > 0,
                detail=(
                    f"Активных источников: {facts.active_sources}."
                    if facts.active_sources > 0
                    else "Нет ни одного активного source в allowlist."
                ),
                next_command="/source_add",
                next_action="Добавь хотя бы один источник через /source_add <chat_id|@username>.",
            ),
            OperationalCheck(
                key="messages",
                title="сообщения в БД",
                ready=facts.has_messages,
                detail=(
                    f"В БД уже есть {facts.total_messages} сообщений из {facts.chats_with_data} источников."
                    if facts.has_messages
                    else "В БД ещё нет ingest-данных."
                ),
                next_command="/sources",
                next_action="Накопи сообщения из разрешённых чатов или подтяни историю через /fullaccess_sync.",
            ),
            OperationalCheck(
                key="digest_target",
                title="digest target",
                ready=facts.digest_target_configured,
                detail=(
                    f"Канал доставки сохранён: {digest_target_label}."
                    if facts.digest_target_configured
                    else "Канал доставки digest пока не задан."
                ),
                next_command="/digest_target",
                next_action="Задай канал доставки через /digest_target <chat_id|@username>.",
            ),
            OperationalCheck(
                key="memory_layer",
                title="memory layer",
                ready=facts.has_memory_cards,
                detail=memory_detail,
                next_command="/memory_rebuild",
                next_action="Перестрой память через /memory_rebuild.",
            ),
            OperationalCheck(
                key="reply_layer",
                title="reply layer",
                ready=reply_ready,
                detail=reply_detail,
                next_command="/reply",
                next_action="После данных и memory проверь /reply <chat_id|@username>.",
            ),
            OperationalCheck(
                key="reminders_layer",
                title="reminders layer",
                ready=reminders_ready,
                detail=reminders_detail,
                next_command="/reminders_scan",
                next_action="Проверь контур reminders через /reminders_scan.",
            ),
            OperationalCheck(
                key="provider_layer",
                title="provider layer",
                ready=provider_ready,
                detail=provider_detail,
                next_command="/provider_status",
                next_action="Проверь /provider_status и либо настрой provider, либо оставь его выключенным.",
            ),
            OperationalCheck(
                key="fullaccess_layer",
                title="full-access experimental",
                ready=fullaccess_ready,
                detail=fullaccess_detail,
                next_command="/fullaccess_status",
                next_action="Проверь /fullaccess_status и реши, нужен ли manual sync через experimental слой.",
            ),
        )

    def _build_layers(self, facts: OperationalFacts) -> tuple[OperationalCheck, ...]:
        ingest_ready = facts.active_sources > 0 and facts.has_messages
        digest_ready = (
            facts.digest_sources > 0
            and facts.has_messages
            and facts.digest_target_configured
        )
        reply_ready, reply_detail = _reply_check(facts)
        reminders_ready, reminders_detail = _reminders_check(facts)
        provider_ready, provider_detail = _provider_check(facts)
        fullaccess_ready, fullaccess_detail = _fullaccess_check(facts)

        if ingest_ready:
            ingest_detail = (
                f"Есть активные источники и {facts.total_messages} сообщений в локальной БД."
            )
        elif facts.active_sources == 0:
            ingest_detail = "Нет активных источников, ingest пока некуда вести."
        else:
            ingest_detail = "Источники добавлены, но в БД ещё нет сообщений."

        if digest_ready:
            digest_detail = (
                f"Доступно {facts.digest_window_messages} сообщений для окна {facts.digest_window_label}, "
                f"цель: {facts.digest_target_label or 'настроена'}."
            )
        elif facts.digest_sources == 0:
            digest_detail = "Нет ни одного активного digest-источника."
        elif not facts.has_messages:
            digest_detail = "Слой digest настроен, но пока нет входных сообщений."
        else:
            digest_detail = "Нет канала доставки digest."

        memory_ready = facts.has_messages and facts.has_memory_cards
        if memory_ready:
            memory_detail = (
                f"Memory-карт: чатов {facts.chat_memory_cards}, людей {facts.person_memory_cards}."
            )
        elif facts.has_messages:
            memory_detail = "Сообщения уже есть, но memory cards ещё не построены."
        else:
            memory_detail = "Нет данных для построения memory."

        return (
            OperationalCheck(
                key="ingest",
                title="ingest",
                ready=ingest_ready,
                detail=ingest_detail,
                next_command="/source_add",
            ),
            OperationalCheck(
                key="digest",
                title="digest",
                ready=digest_ready,
                detail=digest_detail,
                next_command="/digest_target",
            ),
            OperationalCheck(
                key="memory",
                title="memory",
                ready=memory_ready,
                detail=memory_detail,
                next_command="/memory_rebuild",
            ),
            OperationalCheck(
                key="reply",
                title="reply",
                ready=reply_ready,
                detail=reply_detail,
                next_command="/reply",
            ),
            OperationalCheck(
                key="reminders",
                title="reminders",
                ready=reminders_ready,
                detail=reminders_detail,
                next_command="/reminders_scan",
            ),
            OperationalCheck(
                key="provider",
                title="provider",
                ready=provider_ready,
                detail=provider_detail,
                next_command="/provider_status",
            ),
            OperationalCheck(
                key="fullaccess",
                title="full-access",
                ready=fullaccess_ready,
                detail=fullaccess_detail,
                next_command="/fullaccess_status",
            ),
        )

    def _build_warnings(
        self,
        facts: OperationalFacts,
        checklist: tuple[OperationalCheck, ...],
        layers: tuple[OperationalCheck, ...],
    ) -> list[str]:
        warnings: list[str] = []
        if facts.schema_revision is None:
            warnings.append("Миграции БД не применены.")
        if facts.owner_chat_id is None:
            warnings.append("owner chat неизвестен.")
        if facts.active_sources == 0:
            warnings.append("Нет активных источников.")
        if not facts.has_messages:
            warnings.append("В БД ещё нет сообщений.")
        if not facts.digest_target_configured:
            warnings.append("digest target не задан.")
        if facts.has_messages and not facts.has_memory_cards:
            warnings.append("Есть сообщения, но memory cards ещё не строились.")
        if facts.active_reminders == 0:
            warnings.append("Активных reminders пока нет.")
        if facts.active_reminders > 0 and facts.owner_chat_id is None:
            warnings.append("Есть reminders, но owner chat не задан.")
        if not facts.reminders_worker_ready:
            warnings.append("Worker path reminder_delivery не зарегистрирован.")
        if facts.provider_status.enabled and not facts.provider_status.configured:
            warnings.append(f"Provider layer включён, но не готов: {facts.provider_status.reason}")
        if facts.fullaccess_status is not None and facts.fullaccess_status.enabled and not facts.fullaccess_status.ready_for_manual_sync:
            warnings.append(f"Full-access experimental ещё не готов: {facts.fullaccess_status.reason}")
        if facts.recent_worker_error:
            warnings.append(f"Недавняя ошибка worker: {facts.recent_worker_error}")
        if facts.recent_provider_error:
            warnings.append(f"Недавняя ошибка provider: {facts.recent_provider_error}")
        if facts.recent_fullaccess_error:
            warnings.append(f"Недавняя ошибка full-access: {facts.recent_fullaccess_error}")
        warnings.extend(f"Startup warning: {warning}" for warning in facts.startup_warnings)
        for item in checklist:
            if not item.ready and item.key in {"reply_layer", "reminders_layer"}:
                warnings.append(item.detail)
        for layer in layers:
            if not layer.ready and layer.key in {"digest", "memory"}:
                warnings.append(layer.detail)
        return warnings

    async def _get_provider_status(self) -> ProviderStatus:
        manager = self.provider_manager or ProviderManager.from_settings(Settings())
        return await manager.get_status(check_api=False)


def _reply_check(facts: OperationalFacts) -> tuple[bool, str]:
    if not facts.has_messages:
        return False, "Нет данных для reply."
    if not facts.has_memory_cards:
        return False, "Есть сообщения, но memory cards ещё не построены."
    if not facts.style_ready:
        return False, "Style layer ещё не готов."
    if not facts.persona_ready:
        return False, "Persona/style контур ещё не готов."
    if facts.reply_ready_chats == 0:
        return False, "Недостаточно сообщений в чатах для /reply."
    detail = (
        f"Reply готов: {facts.reply_ready_chats} чатов с контекстом, "
        f"few-shot: {'да' if facts.reply_examples > 0 else 'нет'}."
    )
    return True, detail


def _reminders_check(facts: OperationalFacts) -> tuple[bool, str]:
    if facts.owner_chat_id is None:
        return False, "owner chat не задан, reminders некуда доставлять."
    if not facts.reminders_worker_ready:
        return False, "Worker path reminder_delivery не зарегистрирован."
    if not facts.has_messages:
        return False, "Нет сообщений для reminders_scan."
    detail = (
        f"Контур reminders готов: active reminders {facts.active_reminders}, "
        f"подтверждённых задач {facts.confirmed_tasks}."
    )
    return True, detail


def _provider_check(facts: OperationalFacts) -> tuple[bool, str]:
    status = facts.provider_status
    if not status.enabled:
        return True, "Provider layer выключен, deterministic fallback активен."
    if not status.configured:
        return False, f"Provider layer включён, но не готов: {status.reason}"
    return True, f"Provider layer настроен: {status.provider_name or 'provider'}."


def _fullaccess_check(facts: OperationalFacts) -> tuple[bool, str]:
    status = facts.fullaccess_status
    if status is None or not status.enabled:
        return True, "Experimental full-access выключен."
    if not status.ready_for_manual_sync:
        return False, f"Experimental full-access не готов: {status.reason}"
    return True, (
        f"Experimental full-access готов: синхронизировано чатов {status.synced_chat_count}, "
        f"сообщений {status.synced_message_count}."
    )


def _dedupe(values: Sequence[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _read_string(snapshot, key: str) -> str | None:
    if snapshot is None:
        return None
    value = snapshot.payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_startup_warnings(snapshot, *, prefix: str) -> list[str]:
    if snapshot is None:
        return []
    warnings = snapshot.payload.get("warnings")
    if not isinstance(warnings, list):
        return []
    result: list[str] = []
    for item in warnings:
        if isinstance(item, str) and item.strip():
            result.append(f"{prefix}: {item.strip()}")
    return result
