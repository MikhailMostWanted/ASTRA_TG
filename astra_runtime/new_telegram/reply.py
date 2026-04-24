from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.reply_payload import build_reply_context_payload, decorate_reply_payload
from services.reply_service_factory import build_reply_service
from services.reply_workspace_types import ReplyWorkspaceChat, ReplyWorkspaceMessage
from storage.repositories import ChatRepository


DEFAULT_REPLY_WORKSPACE_LIMIT = 80


class NewTelegramReplyWorkspace:
    def __init__(
        self,
        *,
        settings,
        session_factory: async_sessionmaker[AsyncSession] | None,
        history,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.history = history

    def route_ready(self) -> bool:
        return self.settings is not None and self.session_factory is not None and self.history.route_ready()

    def route_reason(self) -> str | None:
        if self.settings is None:
            return "New Telegram reply workspace requires application settings."
        if self.session_factory is None:
            return "New Telegram reply workspace requires local storage runtime."
        return self.history.route_reason()

    async def build_reply_result(
        self,
        reference: str,
        *,
        use_provider_refinement: bool | None = None,
        workspace_messages: tuple[Any, ...] | None = None,
    ):
        if self.session_factory is None:
            raise RuntimeError("New Telegram reply workspace requires local storage runtime.")

        async with self.session_factory() as session:
            service = build_reply_service(self.settings, session)
            if workspace_messages is not None:
                chat = await ChatRepository(session).find_chat_by_handle_or_telegram_id(reference)
                if chat is None:
                    return await service.build_reply(
                        reference,
                        use_provider_refinement=use_provider_refinement,
                    )
                return await service.build_reply_for_chat(
                    chat,
                    reference=reference,
                    use_provider_refinement=use_provider_refinement,
                    workspace_messages=workspace_messages,
                    source_backend="legacy",
                )
            return await service.build_reply(
                reference,
                use_provider_refinement=use_provider_refinement,
                source_backend="new",
            )

    async def get_reply_preview(
        self,
        chat_id: int,
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        workspace_payload = await self.history.get_chat_workspace(
            chat_id,
            limit=DEFAULT_REPLY_WORKSPACE_LIMIT,
        )
        reply_payload, _reply_context = await self.build_preview_from_workspace(
            workspace_payload,
            use_provider_refinement=use_provider_refinement,
        )
        return reply_payload

    async def enrich_workspace_payload(
        self,
        workspace_payload: dict[str, Any],
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        reply_payload, reply_context = await self.build_preview_from_workspace(
            workspace_payload,
            use_provider_refinement=use_provider_refinement,
        )
        workspace_payload["reply"] = reply_payload
        workspace_payload["replyContext"] = reply_context
        status_payload = workspace_payload.get("status")
        if isinstance(status_payload, dict):
            availability = status_payload.get("availability")
            if isinstance(availability, dict):
                availability["replyContextAvailable"] = bool(reply_context.get("available"))
        return workspace_payload

    async def build_preview_from_workspace(
        self,
        workspace_payload: dict[str, Any],
        *,
        use_provider_refinement: bool | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.session_factory is None:
            raise RuntimeError("New Telegram reply workspace requires local storage runtime.")

        chat_payload = workspace_payload.get("chat")
        message_payloads = workspace_payload.get("messages")
        if not isinstance(chat_payload, dict) or not isinstance(message_payloads, list):
            raise RuntimeError("Workspace payload is malformed for reply generation.")

        workspace_chat = _build_workspace_chat(chat_payload)
        workspace_messages = _build_workspace_messages(
            chat_id=workspace_chat.id,
            message_payloads=message_payloads,
        )
        reference = str(chat_payload.get("reference") or chat_payload.get("telegramChatId") or workspace_chat.id)

        async with self.session_factory() as session:
            service = build_reply_service(self.settings, session)
            workspace_source_backend = _resolve_workspace_source_backend(workspace_payload)
            result = await service.build_reply_for_chat(
                workspace_chat,
                reference=reference,
                use_provider_refinement=use_provider_refinement,
                workspace_messages=workspace_messages,
                source_backend=workspace_source_backend,
                history_payload=workspace_payload.get("history") if isinstance(workspace_payload.get("history"), dict) else None,
                freshness_payload=workspace_payload.get("freshness") if isinstance(workspace_payload.get("freshness"), dict) else None,
                status_payload=workspace_payload.get("status") if isinstance(workspace_payload.get("status"), dict) else None,
            )

        from apps.desktop_api.serializers import serialize_reply_result

        reply_payload = decorate_reply_payload(
            serialize_reply_result(result),
            send_enabled=False,
        )
        reply_context = build_reply_context_payload(
            reply_payload=reply_payload,
            message_payloads=message_payloads,
            source_backend=_resolve_workspace_source_backend(workspace_payload),
        )
        return reply_payload, reply_context


def _build_workspace_chat(chat_payload: dict[str, Any]) -> ReplyWorkspaceChat:
    chat_id = _pick_int(chat_payload, "localChatId")
    runtime_chat_id = _pick_int(chat_payload, "runtimeChatId") or _pick_int(chat_payload, "telegramChatId") or 0
    stable_chat_id = chat_id if chat_id is not None else _pick_int(chat_payload, "id") or runtime_chat_id
    return ReplyWorkspaceChat(
        id=stable_chat_id,
        telegram_chat_id=runtime_chat_id,
        title=str(chat_payload.get("title") or "Чат"),
        handle=_pick_str(chat_payload, "handle"),
        type=str(chat_payload.get("type") or "group"),
        is_enabled=bool(chat_payload.get("enabled")),
        category=_pick_str(chat_payload, "category"),
        summary_schedule=_pick_str(chat_payload, "summarySchedule"),
        reply_assist_enabled=bool(chat_payload.get("replyAssistEnabled")),
        auto_reply_mode=_pick_str(chat_payload, "autoReplyMode"),
        exclude_from_memory=bool(chat_payload.get("excludeFromMemory")),
        exclude_from_digest=bool(chat_payload.get("excludeFromDigest")),
    )


def _build_workspace_messages(
    *,
    chat_id: int,
    message_payloads: list[dict[str, Any]],
) -> tuple[ReplyWorkspaceMessage, ...]:
    stable_ids: dict[int, int] = {}
    for payload in message_payloads:
        runtime_message_id = _pick_int(payload, "runtimeMessageId") or _pick_int(payload, "telegramMessageId") or 0
        local_message_id = _pick_int(payload, "localMessageId")
        stable_ids[runtime_message_id] = _stable_message_id(local_message_id, runtime_message_id)

    messages: list[ReplyWorkspaceMessage] = []
    for payload in message_payloads:
        runtime_message_id = _pick_int(payload, "runtimeMessageId") or _pick_int(payload, "telegramMessageId") or 0
        local_message_id = _pick_int(payload, "localMessageId")
        reply_to_runtime_message_id = _pick_int(payload, "replyToRuntimeMessageId")
        messages.append(
            ReplyWorkspaceMessage(
                id=stable_ids.get(runtime_message_id, _stable_message_id(local_message_id, runtime_message_id)),
                local_message_id=local_message_id,
                runtime_message_id=runtime_message_id,
                message_key=_pick_str(payload, "messageKey"),
                chat_id=chat_id,
                direction=str(payload.get("direction") or "inbound"),
                source_adapter=_pick_str(payload, "sourceAdapter"),
                source_type=_pick_str(payload, "sourceType"),
                sender_id=_pick_int(payload, "senderId"),
                sender_name=_pick_str(payload, "senderName"),
                sent_at=_parse_datetime(_pick_str(payload, "sentAt")),
                raw_text=_pick_str(payload, "text") or "",
                normalized_text=_pick_str(payload, "normalizedText") or _pick_str(payload, "text") or "",
                reply_to_message_id=(
                    stable_ids.get(reply_to_runtime_message_id)
                    if reply_to_runtime_message_id is not None
                    else None
                ),
                reply_to_local_message_id=_pick_int(payload, "replyToLocalMessageId"),
                reply_to_runtime_message_id=reply_to_runtime_message_id,
                has_media=bool(payload.get("hasMedia")),
                media_type=_pick_str(payload, "mediaType"),
            )
        )
    return tuple(messages)


def _stable_message_id(local_message_id: int | None, runtime_message_id: int) -> int:
    if local_message_id is not None:
        return local_message_id
    return 1_000_000_000 + runtime_message_id


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pick_int(payload: dict[str, Any] | None, key: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _pick_str(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _resolve_workspace_source_backend(workspace_payload: dict[str, Any]) -> str:
    status_payload = workspace_payload.get("status")
    if isinstance(status_payload, dict):
        message_source = status_payload.get("messageSource")
        if isinstance(message_source, dict):
            backend = _pick_str(message_source, "backend")
            if backend:
                return backend
        status_source = _pick_str(status_payload, "source")
        if status_source:
            return status_source
    return "new"
