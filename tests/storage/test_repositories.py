import asyncio
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from storage.database import build_database_runtime, bootstrap_database
from storage.repositories import (
    ChatRepository,
    DigestRepository,
    MessageRepository,
    SettingRepository,
    SystemRepository,
)


def test_storage_repositories_cover_basic_crud(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "repositories" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        settings = Settings()
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            digests = DigestRepository(session)
            repo_settings = SettingRepository(session)
            system = SystemRepository(session)

            created_chat = await chats.upsert_chat(
                telegram_chat_id=100500,
                title="Семья",
                handle="family",
                chat_type="group",
                category="private",
                summary_schedule="daily",
                reply_assist_enabled=True,
                auto_reply_mode="manual",
            )
            await session.commit()

            updated_chat = await chats.upsert_chat(
                telegram_chat_id=100500,
                title="Семья и близкие",
                handle="family",
                chat_type="group",
                is_enabled=False,
                exclude_from_digest=True,
            )
            await session.commit()

            fetched_chat = await chats.get_by_telegram_chat_id(100500)
            assert fetched_chat is not None
            assert fetched_chat.id == created_chat.id
            assert updated_chat.title == "Семья и близкие"
            assert updated_chat.is_enabled is False
            assert updated_chat.exclude_from_digest is True

            listed_chats = await chats.list_chats()
            assert [chat.telegram_chat_id for chat in listed_chats] == [100500]

            enabled_chats = await chats.list_enabled_chats()
            assert enabled_chats == []

            fetched_by_handle = await chats.find_chat_by_handle_or_telegram_id("@family")
            assert fetched_by_handle is not None
            assert fetched_by_handle.telegram_chat_id == 100500

            reenabled_chat = await chats.set_chat_enabled("@family", is_enabled=True)
            await session.commit()

            assert reenabled_chat is not None
            assert reenabled_chat.is_enabled is True
            assert [chat.telegram_chat_id for chat in await chats.list_enabled_chats()] == [100500]

            digest_ready_chat = await chats.upsert_chat(
                telegram_chat_id=100500,
                exclude_from_digest=False,
            )
            await session.commit()
            assert digest_ready_chat.exclude_from_digest is False

            first_message = await messages.create_message(
                chat_id=updated_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 15, tzinfo=timezone.utc),
                raw_text="Привет",
                normalized_text="привет",
                has_media=False,
            )
            second_message = await messages.create_message(
                chat_id=updated_chat.id,
                telegram_message_id=2,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
                raw_text="Не забудь купить хлеб",
                normalized_text="не забудь купить хлеб",
                reply_to_message_id=first_message.id,
                has_media=False,
            )
            await session.commit()

            recent_messages = await messages.get_recent_messages(chat_id=updated_chat.id, limit=5)
            assert [message.telegram_message_id for message in recent_messages] == [2, 1]

            fts_messages = await messages.search_full_text("хлеб", limit=5)
            assert [message.telegram_message_id for message in fts_messages] == [2]

            digest = await digests.create_digest(
                chat_id=updated_chat.id,
                window_start=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                summary_short="Короткая сводка",
                summary_long="Подробная сводка",
                delivered_to_chat_id=100500,
                delivered_message_id=22,
                items=[
                    {
                        "source_chat_id": updated_chat.id,
                        "source_message_id": second_message.id,
                        "title": "Покупки",
                        "summary": "Нужно купить хлеб",
                        "sort_order": 1,
                    }
                ],
            )
            await session.commit()

            assert digest.items[0].title == "Покупки"
            assert digest.items[0].source_message_id == second_message.id
            assert await digests.count_digests() == 1
            assert (await digests.get_last_digest()).id == digest.id

            digest_messages = await messages.get_messages_for_digest(
                window_start=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
            )
            assert [item.message.telegram_message_id for item in digest_messages] == [1, 2]

            digest_counts = await messages.count_messages_by_digest_chat(
                window_start=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
            )
            assert digest_counts == {updated_chat.id: 2}

            delivered_digest = await digests.mark_delivered(
                digest.id,
                delivered_to_chat_id=200700,
                delivered_message_id=99,
            )
            await session.commit()
            assert delivered_digest is not None
            assert delivered_digest.delivered_to_chat_id == 200700
            assert delivered_digest.delivered_message_id == 99

            missing_setting = await repo_settings.get_value("digest.enabled")
            assert missing_setting is None

            saved_setting = await repo_settings.set_value(
                key="digest.enabled",
                value_json={"enabled": True},
            )
            await session.commit()

            fetched_setting = await repo_settings.get_by_key("digest.enabled")
            assert fetched_setting is not None
            assert saved_setting.id == fetched_setting.id
            assert fetched_setting.value_json == {"enabled": True}

            await repo_settings.set_value(
                key="digest.target.label",
                value_text="@astra_digest",
            )
            await session.commit()

            assert await repo_settings.get_value("digest.target.label") == "@astra_digest"
            assert await system.get_schema_revision() == "20260420_01"

        await runtime.dispose()

    asyncio.run(run_assertions())
