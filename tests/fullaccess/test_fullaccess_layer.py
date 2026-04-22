import asyncio
import importlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiogram.filters.command import CommandObject

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.models import FullAccessChatSummary, FullAccessRemoteMessage
from services.status_summary import BotStatusService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReminderRepository,
    ReplyExampleRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
    TaskRepository,
)


@dataclass(slots=True)
class FakeIncomingMessage:
    chat_id: int
    answers: list[str] = field(default_factory=list)
    bot: object = field(init=False)
    chat: object = field(init=False)

    def __post_init__(self) -> None:
        self.bot = SimpleNamespace()
        self.chat = SimpleNamespace(id=self.chat_id, type="private")

    async def answer(self, text: str):
        self.answers.append(text)
        return SimpleNamespace(message_id=1000 + len(self.answers))


class FakeFullAccessClient:
    def __init__(
        self,
        *,
        authorized: bool,
        chats: list[FullAccessChatSummary] | None = None,
        history: dict[str, tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]] | None = None,
    ) -> None:
        self.authorized = authorized
        self.chats = chats or []
        self.history = history or {}
        self.requested_login_phones: list[str] = []
        self.completed_codes: list[str] = []
        self.logged_out = False

    async def is_authorized(self) -> bool:
        return self.authorized

    async def request_login_code(self, phone: str) -> str:
        self.requested_login_phones.append(phone)
        return "hash-123"

    async def complete_login(
        self,
        *,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> bool:
        self.completed_codes.append(code)
        self.authorized = True
        return True

    async def logout(self) -> bool:
        self.logged_out = True
        self.authorized = False
        return True

    async def list_chats(self, *, limit: int) -> list[FullAccessChatSummary]:
        return self.chats[:limit]

    async def fetch_history(
        self,
        reference: str,
        *,
        limit: int,
    ) -> tuple[FullAccessChatSummary, list[FullAccessRemoteMessage]]:
        chat, messages = self.history[reference]
        return chat, messages[:limit]


def test_fullaccess_status_command_reports_disabled_mode(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "fullaccess-disabled" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.delenv("FULLACCESS_ENABLED", raising=False)
        monkeypatch.delenv("FULLACCESS_API_ID", raising=False)
        monkeypatch.delenv("FULLACCESS_API_HASH", raising=False)
        monkeypatch.delenv("FULLACCESS_PHONE", raising=False)

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        management_module = importlib.import_module("bot.handlers.management")
        message = FakeIncomingMessage(chat_id=900)

        await management_module.handle_fullaccess_status_command(
            message,
            runtime.session_factory,
        )

        assert len(message.answers) == 1
        assert "🧪 Full-access" in message.answers[0]
        assert "Экспериментальный read-only слой" in message.answers[0]
        assert "Статус: не авторизован." in message.answers[0]
        assert "[OFF] api_id/api_hash: не настроены" in message.answers[0]
        assert "[OFF] Авторизация: нет" in message.answers[0]
        assert "[OK] Read-only: активен" in message.answers[0]
        assert "FULLACCESS_ENABLED=false" in message.answers[0]

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_fullaccess_login_command_rejects_code_in_bot(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "fullaccess-login-safe" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        management_module = importlib.import_module("bot.handlers.management")
        message = FakeIncomingMessage(chat_id=900)

        await management_module.handle_fullaccess_login_command(
            message,
            CommandObject(prefix="/", command="fullaccess_login", args="12345"),
            runtime.session_factory,
        )

        assert len(message.answers) == 1
        assert "Код нельзя отправлять в чат с ботом." in message.answers[0]
        assert "Войди локально через CLI." in message.answers[0]
        assert "astra fullaccess login" in message.answers[0]
        assert "Обновить" in message.answers[0]

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_fullaccess_status_forces_readonly_barrier(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "fullaccess-readonly" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("FULLACCESS_ENABLED", "true")
        monkeypatch.setenv("FULLACCESS_API_ID", "12345")
        monkeypatch.setenv("FULLACCESS_API_HASH", "hash")
        monkeypatch.setenv("FULLACCESS_PHONE", "+79990000000")
        monkeypatch.setenv("FULLACCESS_READONLY", "false")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        fake_client = FakeFullAccessClient(authorized=False)
        async with runtime.session_factory() as session:
            service = FullAccessAuthService(
                settings=Settings(),
                setting_repository=SettingRepository(session),
                message_repository=MessageRepository(session),
                client_factory=lambda _config: fake_client,
            )
            report = await service.build_status_report()

        assert report.requested_readonly is False
        assert report.effective_readonly is True
        assert "принудительно" in report.reason.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_fullaccess_sync_writes_into_existing_message_store_and_deduplicates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "fullaccess-sync" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("FULLACCESS_ENABLED", "true")
        monkeypatch.setenv("FULLACCESS_API_ID", "12345")
        monkeypatch.setenv("FULLACCESS_API_HASH", "hash")
        monkeypatch.setenv("FULLACCESS_PHONE", "+79990000000")
        monkeypatch.setenv("FULLACCESS_SYNC_LIMIT", "10")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        sync_module = importlib.import_module("fullaccess.sync")

        remote_chat = FullAccessChatSummary(
            telegram_chat_id=-1009876543210,
            title="Команда продукта",
            chat_type="supergroup",
            username="product_team",
        )
        initial_history = [
            FullAccessRemoteMessage(
                telegram_message_id=11,
                sender_id=101,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc),
                raw_text="Когда будет финальный файл?",
                normalized_text="Когда будет финальный файл?",
                reply_to_telegram_message_id=None,
                forward_info=None,
                has_media=False,
                media_type=None,
                entities_json=None,
                source_type="message",
            ),
            FullAccessRemoteMessage(
                telegram_message_id=12,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 21, 8, 5, tzinfo=timezone.utc),
                raw_text="К вечеру добью и скину.",
                normalized_text="К вечеру добью и скину.",
                reply_to_telegram_message_id=11,
                forward_info=None,
                has_media=False,
                media_type=None,
                entities_json=None,
                source_type="message",
            ),
        ]
        updated_history = [
            initial_history[0],
            FullAccessRemoteMessage(
                telegram_message_id=12,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 21, 8, 5, tzinfo=timezone.utc),
                raw_text="К вечеру добью и скину итоговый файл.",
                normalized_text="К вечеру добью и скину итоговый файл.",
                reply_to_telegram_message_id=11,
                forward_info=None,
                has_media=False,
                media_type=None,
                entities_json=None,
                source_type="message",
            ),
        ]

        fake_client = FakeFullAccessClient(
            authorized=True,
            history={"@product_team": (remote_chat, initial_history)},
        )

        async with runtime.session_factory() as session:
            service = sync_module.FullAccessSyncService(
                settings=Settings(),
                chat_repository=ChatRepository(session),
                message_repository=MessageRepository(session),
                client_factory=lambda _config: fake_client,
            )

            first_result = await service.sync_chat("@product_team")
            await session.commit()

            assert first_result.scanned_count == 2
            assert first_result.created_count == 2
            assert first_result.updated_count == 0
            assert first_result.skipped_count == 0
            assert first_result.chat_created is True

            stored_chat = await ChatRepository(session).get_by_telegram_chat_id(remote_chat.telegram_chat_id)
            assert stored_chat is not None
            assert stored_chat.category == "fullaccess"
            assert stored_chat.is_enabled is False
            assert stored_chat.exclude_from_digest is True

            stored_messages = await MessageRepository(session).get_messages_for_chat(
                chat_id=stored_chat.id,
                ascending=True,
            )
            assert [message.telegram_message_id for message in stored_messages] == [11, 12]
            assert {message.source_adapter for message in stored_messages} == {"fullaccess"}

            fake_client.history["@product_team"] = (remote_chat, updated_history)
            second_result = await service.sync_chat("@product_team")
            await session.commit()

            assert second_result.scanned_count == 2
            assert second_result.created_count == 0
            assert second_result.updated_count == 1
            assert second_result.skipped_count == 1

            stored_messages = await MessageRepository(session).get_messages_for_chat(
                chat_id=stored_chat.id,
                ascending=True,
            )
            assert len(stored_messages) == 2
            assert stored_messages[-1].raw_text == "К вечеру добью и скину итоговый файл."

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_status_message_reports_fullaccess_readiness(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "fullaccess-status" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("FULLACCESS_ENABLED", "true")
        monkeypatch.setenv("FULLACCESS_API_ID", "12345")
        monkeypatch.setenv("FULLACCESS_API_HASH", "hash")
        monkeypatch.setenv("FULLACCESS_PHONE", "+79990000000")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        fake_client = FakeFullAccessClient(authorized=True)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            chat = await chats.upsert_chat(
                telegram_chat_id=-100700,
                title="История fullaccess",
                handle="fullaccess_source",
                chat_type="supergroup",
                is_enabled=False,
                category="fullaccess",
                exclude_from_digest=True,
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_id=100,
                sender_name="Анна",
                direction="inbound",
                source_adapter="fullaccess",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
                raw_text="Тестовый import",
                normalized_text="Тестовый import",
            )
            await session.commit()

            fullaccess_service = FullAccessAuthService(
                settings=Settings(),
                setting_repository=SettingRepository(session),
                message_repository=messages,
                client_factory=lambda _config: fake_client,
            )
            status_text = await BotStatusService(
                chat_repository=chats,
                setting_repository=SettingRepository(session),
                system_repository=SystemRepository(session),
                message_repository=messages,
                digest_repository=DigestRepository(session),
                chat_memory_repository=ChatMemoryRepository(session),
                person_memory_repository=PersonMemoryRepository(session),
                style_profile_repository=StyleProfileRepository(session),
                chat_style_override_repository=ChatStyleOverrideRepository(session),
                task_repository=TaskRepository(session),
                reminder_repository=ReminderRepository(session),
                reply_example_repository=ReplyExampleRepository(session),
                fullaccess_auth_service=fullaccess_service,
            ).build_status_message()

        assert "Full-access:" in status_text
        assert "Experimental full-access готов" in status_text
        assert "синхронизировано чатов 1" in status_text

        await runtime.dispose()

    asyncio.run(run_assertions())
