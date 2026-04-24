from __future__ import annotations

from typing import Any, Protocol

from services.reply_models import ReplyResult


class ChatRoster(Protocol):
    """Contract for listing chats visible to Astra control surfaces."""

    async def list_chats(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
    ) -> dict[str, Any]: ...


class MessageHistory(Protocol):
    """Contract for message reads and active-chat tail refresh."""

    async def get_chat_messages(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        before_runtime_message_id: int | None = None,
    ) -> dict[str, Any]: ...

    async def get_chat_workspace(
        self,
        chat_id: int,
        *,
        limit: int = 80,
    ) -> dict[str, Any]: ...


class DraftReplyWorkspace(Protocol):
    """Contract for reply draft generation and preview payloads."""

    async def build_reply_result(
        self,
        reference: str,
        *,
        use_provider_refinement: bool | None = None,
        workspace_messages: tuple[Any, ...] | None = None,
    ) -> ReplyResult: ...

    async def get_reply_preview(
        self,
        chat_id: int,
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]: ...


class MessageSender(Protocol):
    """Contract for outbound Telegram writes."""

    async def send_chat_message(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        reply_to_source_message_id: int | None = None,
        source_message_key: str | None = None,
        reply_to_source_message_key: str | None = None,
        draft_scope_key: str | None = None,
        client_send_id: str | None = None,
    ) -> dict[str, Any]: ...


class AutopilotControlSurface(Protocol):
    """Contract for autopilot settings, state and future actions."""

    async def update_autopilot_global(
        self,
        *,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
    ) -> dict[str, Any]: ...

    async def update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]: ...


class TelegramRuntime(Protocol):
    """Aggregate target runtime used by desktop, bot and future workers."""

    @property
    def chat_roster(self) -> ChatRoster: ...

    @property
    def message_history(self) -> MessageHistory: ...

    @property
    def reply_workspace(self) -> DraftReplyWorkspace: ...

    @property
    def message_sender(self) -> MessageSender: ...

    @property
    def autopilot(self) -> AutopilotControlSurface: ...
