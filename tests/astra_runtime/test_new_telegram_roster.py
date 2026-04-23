import asyncio
from datetime import datetime, timezone
from pathlib import Path

from astra_runtime.new_telegram.config import NewTelegramRuntimeConfig
from astra_runtime.new_telegram.roster import NewTelegramChatRoster
from astra_runtime.new_telegram.transport import (
    NewTelegramDialogMessage,
    NewTelegramDialogSummary,
)
from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, MessageRepository


def test_new_telegram_chat_roster_maps_identity_and_keeps_snapshot_hot(
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'roster.db'}",
            runtime_new_session_path=str(tmp_path / "new-runtime.session"),
        )
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chat = await ChatRepository(session).upsert_chat(
                telegram_chat_id=-100300,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            await MessageRepository(session).create_message(
                chat_id=chat.id,
                telegram_message_id=901,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
                raw_text="Локальный хвост для workspace.",
                normalized_text="Локальный хвост для workspace.",
            )
            await session.commit()

        fake_client = _FakeRosterClient(
            dialogs=(
                NewTelegramDialogSummary(
                    telegram_chat_id=-100500,
                    title="Pinned ops",
                    chat_type="group",
                    username="ops_room",
                    unread_count=7,
                    unread_mentions_count=2,
                    pinned=True,
                    muted=True,
                    archived=False,
                    last_activity_at=datetime(2026, 4, 23, 9, 0, tzinfo=timezone.utc),
                    last_message=NewTelegramDialogMessage(
                        telegram_message_id=333,
                        sender_id=21,
                        sender_name="Ops",
                        direction="inbound",
                        sent_at=datetime(2026, 4, 23, 9, 0, tzinfo=timezone.utc),
                        text="Новый pinned chat виден только через runtime.",
                        has_media=False,
                        media_type=None,
                        source_type="message",
                    ),
                ),
                NewTelegramDialogSummary(
                    telegram_chat_id=-100300,
                    title="Команда продукта",
                    chat_type="group",
                    username="product_team",
                    unread_count=3,
                    unread_mentions_count=0,
                    pinned=False,
                    muted=False,
                    archived=False,
                    last_activity_at=datetime(2026, 4, 23, 8, 30, tzinfo=timezone.utc),
                    last_message=NewTelegramDialogMessage(
                        telegram_message_id=444,
                        sender_id=11,
                        sender_name="Анна",
                        direction="inbound",
                        sent_at=datetime(2026, 4, 23, 8, 30, tzinfo=timezone.utc),
                        text="Runtime превью уже свежее локального хвоста.",
                        has_media=False,
                        media_type=None,
                        source_type="message",
                    ),
                ),
            ),
        )
        roster = NewTelegramChatRoster(
            config=NewTelegramRuntimeConfig(
                enabled=True,
                api_id=1,
                api_hash="hash",
                phone="+79990001122",
                session_path=tmp_path / "new-runtime.session",
                device_name="test-device",
                asset_session_files=(tmp_path / "new-runtime.session",),
                product_surfaces_enabled=True,
            ),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
        )

        first = await roster.list_chats()
        second = await roster.list_chats(search="команда")

        assert fake_client.calls == 1
        assert first["count"] == 2
        assert first["items"][0]["runtimeChatId"] == -100500
        assert first["items"][0]["pinned"] is True
        assert first["items"][0]["unreadCount"] == 7
        assert first["items"][0]["localChatId"] is None
        assert first["items"][0]["workspaceAvailable"] is False
        assert first["items"][0]["id"] < 0

        known = first["items"][1]
        assert known["id"] == known["localChatId"]
        assert known["chatKey"] == "telegram:-100300"
        assert known["workspaceAvailable"] is True
        assert known["lastMessagePreview"] == "Локальный хвост для workspace."
        assert known["rosterLastMessagePreview"] == "Runtime превью уже свежее локального хвоста."
        assert known["rosterSource"] == "new"
        assert known["rosterFreshness"]["mode"] == "fresh"

        assert second["count"] == 1
        assert second["items"][0]["runtimeChatId"] == -100300

        await runtime.dispose()

    asyncio.run(run_assertions())


class _FakeRosterClient:
    def __init__(self, dialogs: tuple[NewTelegramDialogSummary, ...]) -> None:
        self.dialogs = dialogs
        self.calls = 0

    async def list_dialogs(self, *, limit: int) -> tuple[NewTelegramDialogSummary, ...]:
        self.calls += 1
        return self.dialogs[:limit]
