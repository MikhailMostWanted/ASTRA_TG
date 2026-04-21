from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.bot_owner import BotOwnerService
from services.digest_target import DigestTargetService
from services.providers.manager import ProviderManager
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
            "Статус Astra AFT",
            "",
            f"Готово: {report.ready_check_count}/{report.total_check_count}",
            (
                f"Источники: {facts.active_sources} активных, "
                f"сообщений {facts.total_messages}, источников с данными {facts.chats_with_data}"
            ),
            (
                f"Digest: {'готов' if digest_status.ready else 'не готов'}; "
                f"target: {facts.digest_target_label or 'не задан'}"
            ),
            (
                f"Memory: {'готов' if memory_status.ready else 'не готов'}; "
                f"карт чатов {facts.chat_memory_cards}, людей {facts.person_memory_cards}"
            ),
            f"Reply: {'готов' if reply_status.ready else 'не готов'}",
            (
                f"Reminders: {'готов' if reminders_status.ready else 'не готов'}; "
                f"owner chat: {facts.owner_chat_id if facts.owner_chat_id is not None else 'не задан'}"
            ),
            f"Provider: {provider_status.detail}",
            f"Full-access: {fullaccess_status.detail}",
            f"Следующий шаг: {next_step}",
            "Подробно: /onboarding, /checklist, /doctor",
        ]
        return "\n".join(lines)

    async def build_checklist_message(self) -> str:
        report = await self._build_operational_report()
        lines = ["Checklist Astra AFT", ""]
        for item in report.checklist:
            lines.append(_format_check(item))
        lines.extend(
            [
                "",
                "Подробная сводка: /status",
                "Диагностика и предупреждения: /doctor",
            ]
        )
        return "\n".join(lines)

    async def build_doctor_message(self) -> str:
        report = await self._build_operational_report()
        doctor = SystemHealthService().build_report(report)
        lines = ["Doctor Astra AFT", "", "ОК"]
        lines.extend(f"• {item}" for item in doctor.ok_items)
        lines.extend(["", "Предупреждения"])
        lines.extend(f"• {item}" for item in doctor.warnings)
        lines.extend(["", "Что исправить дальше"])
        for index, step in enumerate(doctor.next_steps, start=1):
            lines.append(f"{index}. {step}")
        return "\n".join(lines)

    async def build_provider_status_message(self) -> str:
        status = await self._get_provider_status(check_api=True)
        lines = [
            "Provider layer Astra AFT",
            "",
            f"Слой: {'включён' if status.enabled else 'выключен'}",
            f"Провайдер: {status.provider_name or 'не выбран'}",
            f"Модель fast: {status.model_fast or 'не задана'}",
            f"Модель deep: {status.model_deep or 'не задана'}",
            f"Таймаут: {status.timeout_seconds:.1f}s",
            "API: доступен" if status.available else "API: недоступен",
            (
                "LLM refine для reply: включён"
                if status.reply_refine_enabled
                else "LLM refine для reply: выключен"
            ),
            (
                "LLM refine для digest: включён"
                if status.digest_refine_enabled
                else "LLM refine для digest: выключен"
            ),
            (
                "Reply refine runtime: доступен"
                if status.reply_refine_available
                else "Reply refine runtime: недоступен"
            ),
            (
                "Digest refine runtime: доступен"
                if status.digest_refine_available
                else "Digest refine runtime: недоступен"
            ),
            f"Причина: {status.reason}",
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
                "Разрешённые источники пока не настроены.\n\n"
                "Используй /source_add <chat_id или @username> "
                "или перешли сообщение из нужного канала/группы."
            ]

        sections: list[str] = []
        for index, chat in enumerate(chats, start=1):
            lines = [
                f"{index}. {chat.title}",
                f"ID Telegram: {chat.telegram_chat_id}",
                f"Тип: {chat.type}",
                f"статус: {'активен' if chat.is_enabled else 'выключен'}",
                f"Сообщений: {message_counts.get(chat.id, 0)}",
            ]
            if chat.handle:
                lines.append(f"Username: @{chat.handle}")
            if chat.category:
                lines.append(f"Категория: {chat.category}")
            lines.append(
                f"Исключён из digest: {'да' if chat.exclude_from_digest else 'нет'}"
            )
            lines.append(
                f"Исключён из memory: {'да' if chat.exclude_from_memory else 'нет'}"
            )
            sections.append("\n".join(lines))

        return _chunk_sections(
            title="Разрешённые источники",
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
        ).build_report()

    async def _get_provider_status(self, *, check_api: bool):
        manager = self.provider_manager or ProviderManager.from_settings(Settings())
        return await manager.get_status(check_api=check_api)


def _format_check(item: OperationalCheck) -> str:
    prefix = "[готово]" if item.ready else "[не готово]"
    tail = f" Следующая команда: {item.next_command}" if not item.ready and item.next_command else ""
    return f"{prefix} {item.title} — {item.detail}{tail}"


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
