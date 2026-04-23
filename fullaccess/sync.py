from __future__ import annotations

# LEGACY_RUNTIME: temporary full-access history sync. New history refresh should
# be implemented behind `astra_runtime.contracts.MessageHistory`.

from dataclasses import dataclass
from datetime import UTC, datetime

from config.settings import Settings
from core.logging import get_logger, log_event
from fullaccess.client import (
    FullAccessClientFactory,
    build_fullaccess_client,
    telethon_is_available,
)
from fullaccess.copy import LOCAL_LOGIN_COMMAND
from fullaccess.models import (
    FullAccessChatListResult,
    FullAccessChatSummary,
    FullAccessConfig,
    FullAccessRemoteMessage,
    FullAccessSyncResult,
)
from services.operational_state import OperationalStateService
from storage.repositories import ChatRepository, MessageRepository, SettingRepository


CHAT_LIST_LIMIT = 25
LOGGER = get_logger(__name__)


@dataclass(slots=True)
class FullAccessSyncService:
    settings: Settings
    chat_repository: ChatRepository
    message_repository: MessageRepository
    setting_repository: SettingRepository | None = None
    client_factory: FullAccessClientFactory = build_fullaccess_client
    transport_available: bool | None = None

    async def list_chats(self, *, limit: int = CHAT_LIST_LIMIT) -> FullAccessChatListResult:
        config = await self._require_read_ready_config()
        chats = await self.client_factory(config).list_chats(limit=limit + 1)
        truncated = len(chats) > limit
        visible_chats = tuple(chats[:limit])
        return FullAccessChatListResult(
            chats=visible_chats,
            truncated=truncated,
            returned_count=len(visible_chats),
        )

    async def sync_chat(self, reference: str, *, trigger: str = "manual") -> FullAccessSyncResult:
        config = await self._require_read_ready_config()
        existing_chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
        latest_local_message_id = (
            await self.message_repository.get_latest_telegram_message_id(chat_id=existing_chat.id)
            if existing_chat is not None
            else None
        )
        log_event(
            LOGGER,
            20,
            "fullaccess.sync.started",
            "Начат ручной full-access sync.",
            reference=reference,
            sync_limit=config.sync_limit,
            latest_local_message_id=latest_local_message_id,
        )
        chat_summary, remote_messages = await self.client_factory(config).fetch_history(
            reference,
            limit=config.sync_limit,
            min_message_id=latest_local_message_id,
        )
        local_chat, chat_created = await self._upsert_chat(chat_summary)

        scanned_count = 0
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for remote_message in remote_messages:
            scanned_count += 1
            if not remote_message.raw_text and not remote_message.has_media:
                skipped_count += 1
                continue

            reply_to_message_id = await self._resolve_reply_to_message_id(
                chat_id=local_chat.id,
                remote_message=remote_message,
            )
            existing = await self.message_repository.get_by_chat_and_telegram_message_id(
                chat_id=local_chat.id,
                telegram_message_id=remote_message.telegram_message_id,
            )
            if existing is not None and _messages_match(
                existing=existing,
                remote_message=remote_message,
                reply_to_message_id=reply_to_message_id,
            ):
                skipped_count += 1
                continue

            upsert_result = await self.message_repository.create_or_update_message(
                chat_id=local_chat.id,
                telegram_message_id=remote_message.telegram_message_id,
                sender_id=remote_message.sender_id,
                sender_name=remote_message.sender_name,
                direction=remote_message.direction,
                source_adapter="fullaccess",
                source_type=remote_message.source_type,
                sent_at=remote_message.sent_at,
                raw_text=remote_message.raw_text,
                normalized_text=remote_message.normalized_text,
                reply_to_message_id=reply_to_message_id,
                forward_info=remote_message.forward_info,
                has_media=remote_message.has_media,
                media_type=remote_message.media_type,
                entities_json=remote_message.entities_json,
            )
            if upsert_result.created:
                created_count += 1
            else:
                updated_count += 1

        if self.setting_repository is not None:
            operational_state = OperationalStateService(self.setting_repository)
            await operational_state.record_fullaccess_sync(
                reference=reference,
                scanned_count=scanned_count,
                created_count=created_count,
                updated_count=updated_count,
                skipped_count=skipped_count,
                trigger=trigger,
            )
            await operational_state.record_fullaccess_chat_sync(
                local_chat_id=local_chat.id,
                telegram_chat_id=chat_summary.telegram_chat_id,
                reference=reference,
                scanned_count=scanned_count,
                created_count=created_count,
                updated_count=updated_count,
                skipped_count=skipped_count,
                trigger=trigger,
            )
        log_event(
            LOGGER,
            20,
            "fullaccess.sync.completed",
            "Ручной full-access sync завершён.",
            reference=reference,
            scanned_count=scanned_count,
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            local_chat_id=local_chat.id,
        )
        return FullAccessSyncResult(
            chat=chat_summary,
            local_chat_id=local_chat.id,
            chat_created=chat_created,
            scanned_count=scanned_count,
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
        )

    async def _require_read_ready_config(self) -> FullAccessConfig:
        config = FullAccessConfig.from_settings(self.settings)
        if not config.enabled:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Experimental full-access слой выключен. Включи FULLACCESS_ENABLED=true."
            )
            raise ValueError("Experimental full-access слой выключен. Включи FULLACCESS_ENABLED=true.")
        if not config.api_credentials_configured:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Сначала задай FULLACCESS_API_ID и FULLACCESS_API_HASH.",
            )
            raise ValueError("Сначала задай FULLACCESS_API_ID и FULLACCESS_API_HASH.")
        if not _transport_available(self.client_factory, self.transport_available):
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'."
            )
            raise ValueError(
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'."
            )
        try:
            authorized = await self.client_factory(config).is_authorized()
        except (RuntimeError, ValueError) as error:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                f"Не удалось открыть user-session: {error}",
            )
            raise ValueError(f"Не удалось открыть user-session: {error}") from error
        if not authorized:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Пользовательская session не авторизована. "
                "Сначала заверши вход на экране Full-access в Astra Desktop "
                f"или используй резервный путь {LOCAL_LOGIN_COMMAND}."
            )
            raise ValueError(
                "Пользовательская session не авторизована. "
                "Сначала заверши вход на экране Full-access в Astra Desktop "
                f"или используй резервный путь {LOCAL_LOGIN_COMMAND}."
            )
        return config

    async def _upsert_chat(
        self,
        chat_summary: FullAccessChatSummary,
    ):
        existing_chat = await self.chat_repository.get_by_telegram_chat_id(
            chat_summary.telegram_chat_id
        )
        if existing_chat is None:
            chat = await self.chat_repository.upsert_chat(
                telegram_chat_id=chat_summary.telegram_chat_id,
                title=chat_summary.title,
                handle=chat_summary.username,
                chat_type=chat_summary.chat_type,
                is_enabled=False,
                category="fullaccess",
                reply_assist_enabled=False,
                exclude_from_digest=True,
            )
            return chat, True

        chat = await self.chat_repository.upsert_chat(
            telegram_chat_id=chat_summary.telegram_chat_id,
            title=chat_summary.title,
            handle=chat_summary.username,
            chat_type=chat_summary.chat_type,
        )
        if not chat.category:
            chat.category = "fullaccess"
        await self.chat_repository.session.flush()
        return chat, False

    async def _resolve_reply_to_message_id(
        self,
        *,
        chat_id: int,
        remote_message: FullAccessRemoteMessage,
    ) -> int | None:
        if remote_message.reply_to_telegram_message_id is None:
            return None

        reply_to_message = await self.message_repository.get_by_chat_and_telegram_message_id(
            chat_id=chat_id,
            telegram_message_id=remote_message.reply_to_telegram_message_id,
        )
        if reply_to_message is None:
            return None
        return reply_to_message.id


def _transport_available(
    client_factory: FullAccessClientFactory,
    transport_available: bool | None,
) -> bool:
    if transport_available is not None:
        return transport_available
    if client_factory is not build_fullaccess_client:
        return True
    return telethon_is_available()


def _messages_match(
    *,
    existing,
    remote_message: FullAccessRemoteMessage,
    reply_to_message_id: int | None,
) -> bool:
    return (
        existing.sender_id == remote_message.sender_id
        and existing.sender_name == remote_message.sender_name
        and existing.direction == remote_message.direction
        and existing.source_adapter == "fullaccess"
        and existing.source_type == remote_message.source_type
        and _normalize_datetime(existing.sent_at) == _normalize_datetime(remote_message.sent_at)
        and existing.raw_text == remote_message.raw_text
        and existing.normalized_text == remote_message.normalized_text
        and existing.reply_to_message_id == reply_to_message_id
        and existing.forward_info == remote_message.forward_info
        and existing.has_media == remote_message.has_media
        and existing.media_type == remote_message.media_type
        and existing.entities_json == remote_message.entities_json
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _record_fullaccess_error_if_possible(
    setting_repository: SettingRepository | None,
    message: str,
) -> None:
    if setting_repository is None:
        return
    await OperationalStateService(setting_repository).record_error(
        "fullaccess",
        message=message,
    )
    log_event(
        LOGGER,
        30,
        "fullaccess.sync.warning",
        "Full-access sync требует ручного вмешательства.",
        reason=message,
    )
