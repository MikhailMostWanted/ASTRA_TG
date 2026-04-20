from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from services.digest_target import DigestTargetService
from services.digest_window import parse_digest_window
from storage.repositories import (
    ChatRepository,
    ChatMemoryRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    SettingRepository,
    SystemRepository,
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

    async def build_status_message(self) -> str:
        total_sources = await self.chat_repository.count_chats()
        enabled_sources = await self.chat_repository.count_enabled_chats()
        digest_sources = await self.chat_repository.count_digest_enabled_chats()
        total_messages = await self.message_repository.count_messages()
        message_counts = await self.message_repository.count_messages_by_chat()
        last_message_at = await self.message_repository.get_last_message_timestamp()
        total_digests = await self.digest_repository.count_digests()
        last_digest = await self.digest_repository.get_last_digest()
        total_chat_memory = await self.chat_memory_repository.count_chat_memory()
        total_people_memory = await self.person_memory_repository.count_people_memory()
        last_memory_rebuild = await self.setting_repository.get_value("memory.last_rebuild_at")
        if last_memory_rebuild is None:
            last_memory_rebuild = (
                await self.chat_memory_repository.get_last_updated_at()
                or await self.person_memory_repository.get_last_updated_at()
            )
        digest_target = await DigestTargetService(self.setting_repository).get_target()
        schema_revision = await self.system_repository.get_schema_revision()
        digest_window = parse_digest_window(None)
        digest_window_counts = await self.message_repository.count_messages_by_digest_chat(
            window_start=digest_window.start,
            window_end=digest_window.end,
        )
        digest_window_messages = sum(digest_window_counts.values())
        has_memory_input = total_messages > 0 and bool(message_counts)

        lines = [
            "Статус Astra AFT",
            "",
            "Бот: жив",
            "Хранилище: SQLite",
            "Ingest: активен",
            f"Всего источников: {total_sources}",
            f"Активных источников: {enabled_sources}",
            f"Digest-источников: {digest_sources}",
            f"Сохранено сообщений: {total_messages}",
            f"Источников с данными: {len(message_counts)}",
            f"Последнее сообщение: {_format_timestamp(last_message_at)}",
            f"Создано digest: {total_digests}",
            f"Последний digest: {_format_timestamp(last_digest.created_at if last_digest else None)}",
            (
                f"Данных для digest ({digest_window.label}): да "
                f"({digest_window_messages} сообщений из {len(digest_window_counts)} источников)"
                if digest_window_messages
                else f"Данных для digest ({digest_window.label}): нет"
            ),
            f"Memory-карт чатов: {total_chat_memory}",
            f"Memory-карт людей: {total_people_memory}",
            (
                f"Последний rebuild memory: {_format_timestamp(last_memory_rebuild)}"
                if last_memory_rebuild is not None
                else "Последний rebuild memory: ещё не выполнялся"
            ),
            (
                f"Данных для memory: да ({total_messages} сообщений из {len(message_counts)} источников)"
                if has_memory_input
                else "Данных для memory: нет"
            ),
            (
                f"Канал доставки digest: настроен ({digest_target.label or digest_target.chat_id})"
                if digest_target.is_configured
                else "Канал доставки digest: не настроен"
            ),
            f"Схема БД: {schema_revision or 'не применена'}",
        ]
        return "\n".join(lines)

    async def build_settings_message(self) -> str:
        digest_target = await DigestTargetService(self.setting_repository).get_target()
        lines = [
            "Базовые настройки Astra AFT",
            "",
            f"digest_target_chat_id: {digest_target.chat_id if digest_target.chat_id is not None else 'не задан'}",
            f"digest_target_label: {digest_target.label or 'не задан'}",
            f"digest_target_type: {digest_target.chat_type or 'не задан'}",
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
