from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.bot_owner import BotOwnerService
from services.digest_target import DigestTargetService
from services.providers.manager import ProviderManager
from services.render_cards import (
    MARKER_EXP,
    MARKER_OFF,
    MARKER_OK,
    MARKER_OPT,
    MARKER_WARN,
    compact_text,
    format_status_line,
    ready_marker,
    state_shell_lines,
)
from services.system_health import SystemHealthService
from services.system_readiness import OperationalCheck, OperationalReport, SystemReadinessService
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


@dataclass(slots=True)
class BotStatusService:
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

    async def build_status_message(self) -> str:
        report = await self._build_operational_report()
        facts = report.facts
        digest_status = _find_check(report.layers, "digest")
        memory_status = _find_check(report.layers, "memory")
        reply_status = _find_check(report.layers, "reply")
        reminders_status = _find_check(report.layers, "reminders")
        provider_status = _find_check(report.layers, "provider")
        fullaccess_status = _find_check(report.layers, "fullaccess")
        next_step = report.next_steps[0] if report.next_steps else (
            "Критичных блокеров нет. Можно использовать /digest_now, /reply и /reminders_scan."
        )

        lines = [
            "✅ Короткий статус",
            "",
            (
                f"✅ Основной путь готов: {report.ready_check_count}/{report.total_check_count}."
                if report.ready_check_count == report.total_check_count
                else f"⚠️ Готово: {report.ready_check_count}/{report.total_check_count}."
            ),
            f"📂 Источники: {facts.active_sources} активных, сообщений {facts.total_messages}.",
            f"📰 Дайджест: {facts.digest_target_label or 'получатель не задан'}.",
            f"🧠 Память / 💬 ответы / ⏰ напоминания: {facts.chat_memory_cards} / {facts.reply_ready_chats} / {facts.active_reminders}.",
            "",
            "Следующий шаг",
            next_step,
            "",
            "Тех. детали",
            format_status_line(
                ready_marker(facts.active_sources > 0 and facts.has_messages),
                "Источники",
                f"{facts.active_sources} активных, сообщений {facts.total_messages}, с данными {facts.chats_with_data}",
            ),
            format_status_line(
                ready_marker(digest_status.ready),
                "Дайджест",
                f"получатель: {facts.digest_target_label or 'не задан'}",
            ),
            format_status_line(
                ready_marker(memory_status.ready),
                "Память",
                f"карт чатов {facts.chat_memory_cards}, людей {facts.person_memory_cards}",
            ),
            format_status_line(ready_marker(reply_status.ready), "Ответы", reply_status.detail),
            format_status_line(
                ready_marker(reminders_status.ready),
                "Напоминания",
                f"личный чат: {facts.owner_chat_id if facts.owner_chat_id is not None else 'не задан'}",
            ),
            format_status_line(_optional_marker(provider_status), "Провайдер", provider_status.detail),
            format_status_line(_experimental_marker(fullaccess_status), "Full-access", fullaccess_status.detail),
            format_status_line(MARKER_OK, "Операции", _build_ops_status_line(facts)),
            "",
            "Дальше",
            "/setup, /checklist, /doctor",
        ]
        return "\n".join(lines)

    async def build_checklist_message(self) -> str:
        report = await self._build_operational_report()
        lines = [
            "🛠️ Чеклист",
            "",
            f"Закрыто шагов: {report.ready_check_count}/{report.total_check_count}.",
            f"Сейчас мешает: {_first_unready_title(report)}.",
            "",
            "Шаги",
        ]
        for index, item in enumerate(report.checklist, start=1):
            lines.append(_format_check(index=index, item=item))
        lines.extend(
            [
                "",
                "Следующий шаг",
                report.next_steps[0] if report.next_steps else "Основной путь готов.",
                "",
                "Дальше",
                "/status, /doctor",
            ]
        )
        return "\n".join(lines)

    async def build_doctor_message(self) -> str:
        report = await self._build_operational_report()
        doctor = SystemHealthService().build_report(report)
        facts = report.facts
        lines = [
            "🛠️ Доктор",
            "",
            f"ОК-пунктов: {len(doctor.ok_items)}.",
            f"Предупреждений: {len(doctor.warnings)}.",
            "",
            "Что уже ок",
        ]
        lines.extend(f"{MARKER_OK} {compact_text(item, limit=86)}" for item in doctor.ok_items[:6])
        lines.extend(["", "На что смотреть"])
        lines.extend(
            f"{_doctor_warning_marker(item)} {compact_text(item, limit=86)}"
            for item in doctor.warnings[:8]
        )
        hidden_warning_count = max(len(doctor.warnings) - 8, 0)
        if hidden_warning_count:
            lines.append(f"{MARKER_WARN} Ещё предупреждений: {hidden_warning_count}")
        lines.extend(["", "Операции"])
        lines.append(format_status_line(ready_marker(facts.backup_tool_available), "Бэкап", "доступен" if facts.backup_tool_available else "недоступен"))
        lines.append(format_status_line(ready_marker(facts.export_tool_available), "Экспорт", "доступен" if facts.export_tool_available else "недоступен"))
        lines.append(format_status_line(MARKER_OK if facts.last_backup_at else MARKER_OFF, "Последний бэкап", _format_timestamp(facts.last_backup_at)))
        lines.append(format_status_line(MARKER_OK if facts.last_export_at else MARKER_OFF, "Последний экспорт", _format_timestamp(facts.last_export_at)))
        lines.append(format_status_line(MARKER_OK if facts.last_fullaccess_sync_at else MARKER_OFF, "Последний full-access sync", _format_timestamp(facts.last_fullaccess_sync_at)))
        lines.append(format_status_line(MARKER_WARN if facts.recent_worker_error else MARKER_OK, "Последняя ошибка worker", facts.recent_worker_error or "нет"))
        lines.append(format_status_line(MARKER_WARN if facts.recent_provider_error else MARKER_OK, "Последняя ошибка provider", facts.recent_provider_error or "нет"))
        lines.append(format_status_line(MARKER_WARN if facts.recent_fullaccess_error else MARKER_OK, "Последняя ошибка full-access", facts.recent_fullaccess_error or "нет"))
        if facts.startup_warnings:
            lines.extend(format_status_line(MARKER_WARN, "Startup", item) for item in facts.startup_warnings[:4])
        else:
            lines.append(format_status_line(MARKER_OK, "Startup warnings", "нет"))
        lines.extend(["", "Что исправить дальше"])
        for index, step in enumerate(doctor.next_steps, start=1):
            lines.append(f"{index}. {compact_text(step, limit=92)}")
        return "\n".join(lines)

    async def build_provider_status_message(self) -> str:
        status = await self._get_provider_status(check_api=True)
        lines = [
            "🔌 Провайдер",
            "",
            f"Слой: {'включён' if status.enabled else 'выключен'}.",
            f"API: {'доступен' if status.available else 'недоступен'}.",
            "Без провайдера основной путь всё равно работает.",
            "",
            "Тех. детали",
            format_status_line(_provider_detail_marker(status.enabled, status.configured), "Конфиг", "настроен" if status.configured else "не настроен"),
            format_status_line(MARKER_OK if status.provider_name else MARKER_OFF, "Провайдер", status.provider_name or "не выбран"),
            format_status_line(_provider_detail_marker(status.enabled, status.reply_refine_available), "Улучшение ответов", "доступно" if status.reply_refine_available else "недоступно"),
            format_status_line(_provider_detail_marker(status.enabled, status.digest_refine_available), "Улучшение дайджеста", "доступно" if status.digest_refine_available else "недоступно"),
            format_status_line(MARKER_OK if status.enabled and status.available else MARKER_WARN if status.enabled else MARKER_OFF, "Причина", status.reason),
            "",
            "Следующий шаг",
            "Основной путь работает и без провайдера." if not status.enabled else "/provider_status",
        ]
        return "\n".join(lines)

    async def build_settings_message(self) -> str:
        digest_target = await DigestTargetService(self.setting_repository).get_target()
        owner_chat_id = await BotOwnerService(self.setting_repository).get_owner_chat_id()
        lines = [
            "Базовые настройки Astra AFT",
            "",
            f"digest_target_chat_id: {digest_target.chat_id if digest_target.chat_id is not None else 'не задан'}",
            f"digest_target_label: {digest_target.label or 'не задан'}",
            f"digest_target_type: {digest_target.chat_type or 'не задан'}",
            f"bot.owner_chat_id: {owner_chat_id if owner_chat_id is not None else 'не задан'}",
        ]
        return "\n".join(lines)

    async def build_sources_messages(self, *, max_message_length: int = 3500) -> list[str]:
        chats = await self.chat_repository.list_chats()
        message_counts = await self.message_repository.count_messages_by_chat()
        if not chats:
            return [
                "\n".join(
                    [
                        "📂 Источники",
                        "",
                        *state_shell_lines(
                            marker=MARKER_WARN,
                            status="Источники не добавлены",
                            meaning="Astra пока не получает сообщения для digest, memory и reply.",
                            next_step="/source_add <chat_id|@username>",
                        ),
                    ]
                )
            ]

        sections: list[str] = []
        for index, chat in enumerate(chats, start=1):
            lines = [
                f"{index}. {chat.title}",
                format_status_line(MARKER_OK if chat.is_enabled else MARKER_OFF, "Статус", "активен" if chat.is_enabled else "выключен"),
                format_status_line(MARKER_OK if message_counts.get(chat.id, 0) > 0 else MARKER_WARN, "Сообщений", str(message_counts.get(chat.id, 0))),
                f"ID Telegram: {chat.telegram_chat_id}",
                f"Тип: {chat.type}",
            ]
            if chat.handle:
                lines.append(f"Юзернейм: @{chat.handle}")
            if chat.category:
                lines.append(f"Категория: {chat.category}")
            lines.append(
                f"Исключён из дайджеста: {'да' if chat.exclude_from_digest else 'нет'}"
            )
            lines.append(
                f"Исключён из памяти: {'да' if chat.exclude_from_memory else 'нет'}"
            )
            sections.append("\n".join(lines))

        return _chunk_sections(
            title="📂 Источники",
            sections=sections,
            max_message_length=max_message_length,
        )

    async def _build_operational_report(self) -> OperationalReport:
        return await SystemReadinessService(
            chat_repository=self.chat_repository,
            setting_repository=self.setting_repository,
            system_repository=self.system_repository,
            message_repository=self.message_repository,
            digest_repository=self.digest_repository,
            chat_memory_repository=self.chat_memory_repository,
            person_memory_repository=self.person_memory_repository,
            style_profile_repository=self.style_profile_repository,
            chat_style_override_repository=self.chat_style_override_repository,
            task_repository=self.task_repository,
            reminder_repository=self.reminder_repository,
            reply_example_repository=self.reply_example_repository,
            provider_manager=self.provider_manager,
            fullaccess_auth_service=self.fullaccess_auth_service,
            settings=self.settings,
        ).build_report()

    async def _get_provider_status(self, *, check_api: bool):
        manager = self.provider_manager or ProviderManager.from_settings(Settings())
        return await manager.get_status(check_api=check_api)


def _format_check(*, index: int, item: OperationalCheck) -> str:
    marker = _check_marker(item)
    tail = f"; дальше: {item.next_command}" if not item.ready and item.next_command else ""
    return f"{index}. {marker} {_check_title(item)}: {item.detail.rstrip('.')}{tail}"


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
        "digest_target": "Получатель дайджеста",
        "memory_layer": "Память",
        "reply_layer": "Ответы",
        "reminders_layer": "Напоминания",
        "provider_layer": "Провайдер",
        "fullaccess_layer": "Full-access",
    }
    return titles.get(item.key, item.title)


def _first_unready_title(report: OperationalReport) -> str:
    for item in report.checklist:
        if not item.ready:
            return _check_title(item)
    return "всё готово"


def _optional_marker(item: OperationalCheck) -> str:
    if item.ready and "выключен" in item.detail.lower():
        return MARKER_OFF
    return MARKER_OPT if item.ready else MARKER_WARN


def _experimental_marker(item: OperationalCheck) -> str:
    if item.ready and "выключен" in item.detail.lower():
        return MARKER_OFF
    return MARKER_EXP if item.ready else MARKER_WARN


def _provider_detail_marker(enabled: bool, ready: bool) -> str:
    if ready:
        return MARKER_OK
    return MARKER_WARN if enabled else MARKER_OFF


def _doctor_warning_marker(value: str) -> str:
    return MARKER_OK if "критичных проблем не найдено" in value.lower() else MARKER_WARN


def _find_check(report: tuple[OperationalCheck, ...], key: str) -> OperationalCheck:
    for item in report:
        if item.key == key:
            return item
    raise KeyError(key)


def _chunk_sections(
    *,
    title: str,
    sections: list[str],
    max_message_length: int,
) -> list[str]:
    messages: list[str] = []
    current_parts = [title, ""]

    for section in sections:
        candidate = "\n\n".join([*current_parts, section])
        if len(candidate) > max_message_length and len(current_parts) > 2:
            messages.append("\n\n".join(current_parts))
            current_parts = [title, "", section]
            continue

        current_parts.append(section)

    if len(current_parts) > 2:
        messages.append("\n\n".join(current_parts))

    return messages


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


def _build_ops_status_line(facts) -> str:
    notes: list[str] = []
    if facts.backup_tool_available:
        notes.append("бэкап готов")
    else:
        notes.append("бэкап недоступен")
    if facts.export_tool_available:
        notes.append("экспорт готов")
    recent_errors = [
        label
        for label, message in (
            ("worker", facts.recent_worker_error),
            ("провайдер", facts.recent_provider_error),
            ("full-access", facts.recent_fullaccess_error),
        )
        if message
    ]
    if recent_errors:
        notes.append(f"недавние ошибки: {', '.join(recent_errors)}")
    else:
        notes.append("ошибок недавно нет")
    if facts.startup_warnings:
        notes.append(f"startup warnings: {len(facts.startup_warnings)}")
    return "; ".join(notes)
