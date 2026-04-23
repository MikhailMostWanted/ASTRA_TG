from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings
from core.logging import get_logger, log_event
from fullaccess.client import (
    FullAccessClientFactory,
    build_fullaccess_client,
    telethon_is_available,
)
from fullaccess.copy import LOCAL_LOGIN_COMMAND
from fullaccess.models import FullAccessConfig, FullAccessSendResult
from services.operational_state import OperationalStateService
from storage.repositories import ChatRepository, MessageRepository, SettingRepository


LOGGER = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FullAccessLocalSendResult:
    local_chat_id: int
    telegram_chat_id: int
    sent_message_id: int
    remote_result: FullAccessSendResult


@dataclass(slots=True)
class FullAccessSendService:
    settings: Settings
    chat_repository: ChatRepository
    message_repository: MessageRepository
    setting_repository: SettingRepository | None = None
    client_factory: FullAccessClientFactory = build_fullaccess_client
    transport_available: bool | None = None

    async def send_chat_message(
        self,
        chat,
        *,
        text: str,
        reply_to_source_message_id: int | None = None,
        trigger: str = "manual",
    ) -> FullAccessLocalSendResult:
        cleaned_text = " ".join(text.split()).strip()
        if not cleaned_text:
            raise ValueError("Нельзя отправить пустое сообщение.")

        config = await self._require_write_ready_config()
        reference = _build_chat_reference(chat)
        reply_to_message_id = await self._resolve_reply_to_telegram_message_id(
            chat_id=chat.id,
            source_message_id=reply_to_source_message_id,
        )
        log_event(
            LOGGER,
            20,
            "fullaccess.send.started",
            "Начата отправка сообщения через full-access.",
            local_chat_id=chat.id,
            reference=reference,
            trigger=trigger,
            reply_to_source_message_id=reply_to_source_message_id,
        )
        remote_result = await self.client_factory(config).send_message(
            reference,
            text=cleaned_text,
            reply_to_message_id=reply_to_message_id,
        )
        upsert_result = await self.message_repository.create_or_update_message(
            chat_id=chat.id,
            telegram_message_id=remote_result.message.telegram_message_id,
            sender_id=remote_result.message.sender_id,
            sender_name=remote_result.message.sender_name,
            direction=remote_result.message.direction,
            source_adapter="fullaccess",
            source_type=remote_result.message.source_type,
            sent_at=remote_result.message.sent_at,
            raw_text=remote_result.message.raw_text,
            normalized_text=remote_result.message.normalized_text,
            reply_to_message_id=reply_to_source_message_id,
            forward_info=remote_result.message.forward_info,
            has_media=remote_result.message.has_media,
            media_type=remote_result.message.media_type,
            entities_json=remote_result.message.entities_json,
        )
        log_event(
            LOGGER,
            20,
            "fullaccess.send.completed",
            "Сообщение через full-access отправлено.",
            local_chat_id=chat.id,
            reference=reference,
            trigger=trigger,
            telegram_message_id=remote_result.message.telegram_message_id,
            local_message_id=upsert_result.message.id,
        )
        return FullAccessLocalSendResult(
            local_chat_id=chat.id,
            telegram_chat_id=remote_result.chat.telegram_chat_id,
            sent_message_id=upsert_result.message.id,
            remote_result=remote_result,
        )

    async def _require_write_ready_config(self) -> FullAccessConfig:
        config = FullAccessConfig.from_settings(self.settings)
        if not config.enabled:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Experimental full-access слой выключен. Включи FULLACCESS_ENABLED=true.",
            )
            raise ValueError("Experimental full-access слой выключен. Включи FULLACCESS_ENABLED=true.")
        if config.effective_readonly:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "FULLACCESS_READONLY=true: режим записи выключен, отправка недоступна.",
            )
            raise ValueError("FULLACCESS_READONLY=true: режим записи выключен, отправка недоступна.")
        if not config.api_credentials_configured:
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Сначала задай FULLACCESS_API_ID и FULLACCESS_API_HASH.",
            )
            raise ValueError("Сначала задай FULLACCESS_API_ID и FULLACCESS_API_HASH.")
        if not _transport_available(self.client_factory, self.transport_available):
            await _record_fullaccess_error_if_possible(
                self.setting_repository,
                "Telethon не установлен. Установи optional dependency: pip install -e '.[fullaccess]'.",
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
                f"или используй резервный путь {LOCAL_LOGIN_COMMAND}.",
            )
            raise ValueError(
                "Пользовательская session не авторизована. "
                "Сначала заверши вход на экране Full-access в Astra Desktop "
                f"или используй резервный путь {LOCAL_LOGIN_COMMAND}."
            )
        return config

    async def _resolve_reply_to_telegram_message_id(
        self,
        *,
        chat_id: int,
        source_message_id: int | None,
    ) -> int | None:
        if source_message_id is None:
            return None
        message = await self.message_repository.get_by_id(source_message_id)
        if message is None or message.chat_id != chat_id:
            return None
        return message.telegram_message_id


def _build_chat_reference(chat) -> str:
    if getattr(chat, "handle", None):
        return f"@{chat.handle}"
    return str(chat.telegram_chat_id)


def _transport_available(
    client_factory: FullAccessClientFactory,
    transport_available: bool | None,
) -> bool:
    if transport_available is not None:
        return transport_available
    if client_factory is not build_fullaccess_client:
        return True
    return telethon_is_available()


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
