from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LegacyAstraRuntime:
    """Adapter boundary around the temporary pre-pivot Astra runtime.

    New behavior should target the contracts in `astra_runtime.contracts`.
    This class exists so the old desktop/fullaccess/reply/autopilot contour can
    keep running while each surface is replaced behind explicit switches.
    """

    bridge: Any

    @property
    def chat_roster(self) -> "LegacyAstraRuntime":
        return self

    @property
    def message_history(self) -> "LegacyAstraRuntime":
        return self

    @property
    def reply_workspace(self) -> "LegacyAstraRuntime":
        return self

    @property
    def message_sender(self) -> "LegacyAstraRuntime":
        return self

    @property
    def autopilot(self) -> "LegacyAstraRuntime":
        return self

    async def list_chats(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
    ) -> dict[str, Any]:
        return await self.bridge._legacy_list_chats(
            search=search,
            filter_key=filter_key,
            sort_key=sort_key,
        )

    async def get_chat_messages(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        before_runtime_message_id: int | None = None,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_get_chat_messages(
            chat_id,
            limit=limit,
            before_runtime_message_id=before_runtime_message_id,
        )

    async def get_chat_workspace(
        self,
        chat_id: int,
        *,
        limit: int = 80,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_get_chat_workspace(chat_id, limit=limit)

    async def build_reply_result(
        self,
        reference: str,
        *,
        use_provider_refinement: bool | None = None,
        workspace_messages: tuple[Any, ...] | None = None,
    ):
        async with self.bridge.runtime.session_factory() as session:
            return await self.bridge._legacy_build_reply_result(
                session,
                reference,
                use_provider_refinement=use_provider_refinement,
                workspace_messages=workspace_messages,
            )

    async def get_reply_preview(
        self,
        chat_id: int,
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_get_reply_preview(
            chat_id,
            use_provider_refinement=use_provider_refinement,
        )

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
    ) -> dict[str, Any]:
        return await self.bridge._legacy_send_chat_message(
            chat_id,
            text=text,
            source_message_id=source_message_id,
            reply_to_source_message_id=reply_to_source_message_id,
            source_message_key=source_message_key,
            reply_to_source_message_key=reply_to_source_message_key,
            draft_scope_key=draft_scope_key,
            client_send_id=client_send_id,
        )

    async def update_autopilot_global(
        self,
        *,
        mode: str | None = None,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
        emergency_stop: bool | None = None,
        autopilot_paused: bool | None = None,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_update_autopilot_global(
            mode=mode,
            master_enabled=master_enabled,
            allow_channels=allow_channels,
            emergency_stop=emergency_stop,
            autopilot_paused=autopilot_paused,
        )

    async def update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        allowed: bool | None = None,
        autopilot_allowed: bool | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_update_chat_autopilot(
            chat_id,
            trusted=trusted,
            allowed=allowed,
            autopilot_allowed=autopilot_allowed,
            mode=mode,
        )

    async def get_autopilot_status(self, chat_id: int | None = None) -> dict[str, Any]:
        return await self.bridge.get_autopilot_status(chat_id=chat_id)

    async def confirm_autopilot_pending(
        self,
        chat_id: int,
        *,
        pending_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.bridge.confirm_autopilot_pending(chat_id, pending_id=pending_id)

    async def emergency_stop_autopilot(self) -> dict[str, Any]:
        return await self.bridge.emergency_stop_autopilot()

    async def pause_autopilot(self, *, paused: bool = True) -> dict[str, Any]:
        return await self.bridge.pause_autopilot(paused=paused)

    async def list_autopilot_activity(self, *, limit: int = 20) -> dict[str, Any]:
        return await self.bridge.list_autopilot_activity(limit=limit)
