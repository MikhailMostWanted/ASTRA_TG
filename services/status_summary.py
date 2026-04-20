from __future__ import annotations

from dataclasses import dataclass

from services.digest_target import DigestTargetService
from storage.repositories import ChatRepository, SettingRepository, SystemRepository


@dataclass(slots=True)
class BotStatusService:
    chat_repository: ChatRepository
    setting_repository: SettingRepository
    system_repository: SystemRepository

    async def build_status_message(self) -> str:
        total_sources = await self.chat_repository.count_chats()
        enabled_sources = await self.chat_repository.count_enabled_chats()
        digest_target = await DigestTargetService(self.setting_repository).get_target()
        schema_revision = await self.system_repository.get_schema_revision()

        lines = [
            "Статус Astra AFT",
            "",
            "Бот: жив",
            "Хранилище: SQLite",
            f"Всего источников: {total_sources}",
            f"Активных источников: {enabled_sources}",
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
