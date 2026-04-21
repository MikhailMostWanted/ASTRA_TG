import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from services.message_ingest import MessageIngestService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, MessageRepository


@dataclass(slots=True)
class FakeChat:
    id: int
    type: str
    title: str | None = None
    username: str | None = None


@dataclass(slots=True)
class FakeUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


@dataclass(slots=True)
class FakeEntity:
    type: str
    offset: int
    length: int
    url: str | None = None

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, object]:
        payload = {
            "type": self.type,
            "offset": self.offset,
            "length": self.length,
            "url": self.url,
        }
        if exclude_none:
            return {key: value for key, value in payload.items() if value is not None}
        return payload


@dataclass(slots=True)
class FakeForwardOrigin:
    chat: FakeChat | None = None
    sender_user_name: str | None = None

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, object]:
        payload = {
            "chat": {
                "id": self.chat.id,
                "type": self.chat.type,
                "title": self.chat.title,
                "username": self.chat.username,
            }
            if self.chat is not None
            else None,
            "sender_user_name": self.sender_user_name,
        }
        if exclude_none:
            return {key: value for key, value in payload.items() if value is not None}
        return payload


@dataclass(slots=True)
class FakeMessage:
    message_id: int
    chat: FakeChat
    date: datetime
    text: str | None = None
    caption: str | None = None
    from_user: FakeUser | None = None
    sender_chat: FakeChat | None = None
    reply_to_message: "FakeMessage | None" = None
    forward_origin: object | None = None
    entities: list[FakeEntity] | None = None
    caption_entities: list[FakeEntity] | None = None
    photo: list[object] | None = None
    video: object | None = None
    document: object | None = None


def test_ingest_saves_message_from_allowed_source(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "ingest-allowed" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            chat = await chats.upsert_chat(
                telegram_chat_id=-100200,
                title="Новости",
                chat_type="supergroup",
                is_enabled=True,
            )
            await session.commit()

            service = MessageIngestService(
                chat_repository=chats,
                message_repository=messages,
            )

            root_result = await service.ingest_message(
                FakeMessage(
                    message_id=10,
                    chat=FakeChat(id=-100200, type="supergroup", title="Новости"),
                    date=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                    text="Базовое сообщение",
                    from_user=FakeUser(id=77, first_name="Иван", last_name="Петров"),
                )
            )
            await session.commit()

            result = await service.ingest_message(
                FakeMessage(
                    message_id=11,
                    chat=FakeChat(id=-100200, type="supergroup", title="Новости"),
                    date=datetime(2026, 4, 20, 10, 5, tzinfo=timezone.utc),
                    text="  Привет,\n\nмир  ",
                    from_user=FakeUser(id=77, first_name="Иван", last_name="Петров"),
                    reply_to_message=FakeMessage(
                        message_id=10,
                        chat=FakeChat(id=-100200, type="supergroup", title="Новости"),
                        date=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                    ),
                    forward_origin=FakeForwardOrigin(
                        chat=FakeChat(
                            id=-100201,
                            type="channel",
                            title="Источник форварда",
                            username="forward_source",
                        )
                    ),
                    entities=[FakeEntity(type="bold", offset=0, length=6)],
                )
            )
            await session.commit()

            assert root_result.action == "created"
            assert root_result.message is not None
            assert result.action == "created"
            assert result.message is not None
            assert result.message.chat_id == chat.id
            assert result.message.telegram_message_id == 11
            assert result.message.sender_id == 77
            assert result.message.sender_name == "Иван Петров"
            assert result.message.source_adapter == "telegram"
            assert result.message.source_type == "message"
            assert result.message.raw_text == "  Привет,\n\nмир  "
            assert result.message.normalized_text == "Привет, мир"
            assert result.message.reply_to_message_id == root_result.message.id
            assert result.message.forward_info is not None
            assert result.message.entities_json == [{"type": "bold", "offset": 0, "length": 6}]
            assert await messages.count_messages() == 2

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_ingest_skips_unknown_disabled_and_digest_excluded_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "ingest-filtering" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            service = MessageIngestService(
                chat_repository=chats,
                message_repository=messages,
            )

            await chats.upsert_chat(
                telegram_chat_id=-100300,
                title="Выключенный источник",
                chat_type="group",
                is_enabled=False,
            )
            await chats.upsert_chat(
                telegram_chat_id=-100301,
                title="Без digest",
                chat_type="channel",
                is_enabled=True,
                exclude_from_digest=True,
            )
            await session.commit()

            unknown_result = await service.ingest_message(
                FakeMessage(
                    message_id=1,
                    chat=FakeChat(id=-100999, type="group", title="Неизвестный"),
                    date=datetime(2026, 4, 20, 11, 0, tzinfo=timezone.utc),
                    text="Не сохранять",
                )
            )
            disabled_result = await service.ingest_message(
                FakeMessage(
                    message_id=2,
                    chat=FakeChat(id=-100300, type="group", title="Выключенный источник"),
                    date=datetime(2026, 4, 20, 11, 1, tzinfo=timezone.utc),
                    text="Тоже не сохранять",
                )
            )
            excluded_result = await service.ingest_message(
                FakeMessage(
                    message_id=3,
                    chat=FakeChat(id=-100301, type="channel", title="Без digest"),
                    date=datetime(2026, 4, 20, 11, 2, tzinfo=timezone.utc),
                    text="И это тоже",
                )
            )

            assert unknown_result.action == "ignored"
            assert disabled_result.action == "ignored"
            assert excluded_result.action == "ignored"
            assert await messages.count_messages() == 0

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_ingest_updates_duplicate_message_without_creating_duplicate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "ingest-duplicate" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            await chats.upsert_chat(
                telegram_chat_id=-100400,
                title="Дубликаты",
                chat_type="supergroup",
                is_enabled=True,
            )
            await session.commit()

            service = MessageIngestService(
                chat_repository=chats,
                message_repository=messages,
            )

            first_result = await service.ingest_message(
                FakeMessage(
                    message_id=50,
                    chat=FakeChat(id=-100400, type="supergroup", title="Дубликаты"),
                    date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
                    text="Первая версия",
                )
            )
            await session.commit()

            second_result = await service.ingest_message(
                FakeMessage(
                    message_id=50,
                    chat=FakeChat(id=-100400, type="supergroup", title="Дубликаты"),
                    date=datetime(2026, 4, 20, 12, 1, tzinfo=timezone.utc),
                    text="  Вторая   версия  ",
                )
            )
            await session.commit()

            assert first_result.action == "created"
            assert first_result.message is not None
            assert second_result.action == "updated"
            recent_messages = await messages.get_recent_messages(chat_id=first_result.message.chat_id)
            assert await messages.count_messages() == 1
            assert len(recent_messages) == 1
            assert recent_messages[0].raw_text == "  Вторая   версия  "
            assert recent_messages[0].normalized_text == "Вторая версия"

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_ingest_uses_caption_and_marks_media(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "ingest-caption" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            await chats.upsert_chat(
                telegram_chat_id=-100500,
                title="Фото-канал",
                chat_type="channel",
                is_enabled=True,
            )
            await session.commit()

            service = MessageIngestService(
                chat_repository=chats,
                message_repository=messages,
            )

            result = await service.ingest_message(
                FakeMessage(
                    message_id=70,
                    chat=FakeChat(id=-100500, type="channel", title="Фото-канал"),
                    date=datetime(2026, 4, 20, 13, 0, tzinfo=timezone.utc),
                    caption="\n  Подпись \n к фото  ",
                    caption_entities=[FakeEntity(type="italic", offset=2, length=7)],
                    photo=[object()],
                )
            )
            await session.commit()

            assert result.action == "created"
            assert result.message is not None
            assert result.message.raw_text == "\n  Подпись \n к фото  "
            assert result.message.normalized_text == "Подпись к фото"
            assert result.message.has_media is True
            assert result.message.media_type == "photo"
            assert result.message.entities_json == [{"type": "italic", "offset": 2, "length": 7}]
            assert await messages.count_messages() == 1

        await runtime.dispose()

    asyncio.run(run_assertions())
