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
    ) -> dict[str, Any]:
        return await self.bridge._legacy_get_chat_messages(chat_id, limit=limit)

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
    ) -> dict[str, Any]:
        return await self.bridge._legacy_send_chat_message(
            chat_id,
            text=text,
            source_message_id=source_message_id,
            reply_to_source_message_id=reply_to_source_message_id,
        )

    async def update_autopilot_global(
        self,
        *,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_update_autopilot_global(
            master_enabled=master_enabled,
            allow_channels=allow_channels,
        )

    async def update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        return await self.bridge._legacy_update_chat_autopilot(
            chat_id,
            trusted=trusted,
            mode=mode,
        )
