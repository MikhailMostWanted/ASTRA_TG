import asyncio
from datetime import datetime, timezone
from pathlib import Path

from astra_runtime.chat_identity import build_runtime_only_chat_id
from astra_runtime.new_telegram import (
    NewTelegramChatSummary,
    NewTelegramMessageSender,
    NewTelegramRemoteMessage,
    NewTelegramRuntimeConfig,
    NewTelegramSendResult,
)
from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, MessageRepository


def test_new_telegram_message_sender_sends_text_and_persists_local_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run_assertions() -> None:
        runtime = await _build_runtime(tmp_path, monkeypatch)
        async with runtime.session_factory() as session:
            chat = await ChatRepository(session).upsert_chat(
                telegram_chat_id=-100300,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            source = await MessageRepository(session).create_message(
                chat_id=chat.id,
                telegram_message_id=10,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="new_runtime",
                source_type="message",
                sent_at=datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc),
                raw_text="Когда пришлёшь файл?",
                normalized_text="Когда пришлёшь файл?",
            )
            await session.commit()

        fake_client = _FakeSendClient()
        fake_history = _FakeHistory()
        fake_roster = _FakeRoster()
        sender = NewTelegramMessageSender(
            config=_build_config(tmp_path),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
            history=fake_history,
            roster=fake_roster,
        )

        payload = await sender.send_chat_message(
            chat.id,
            text="  Да, пришлю сегодня.\nПроверю финал.  ",
            source_message_id=source.id,
        )

        assert payload["ok"] is True
        assert payload["backend"] == "new"
        assert payload["sentMessage"]["text"] == "Да, пришлю сегодня.\nПроверю финал."
        assert payload["sentMessage"]["replyToRuntimeMessageId"] == 10
        assert payload["sentMessageIdentity"]["chatKey"] == "telegram:-100300"
        assert payload["sentMessageIdentity"]["runtimeMessageId"] == 501
        assert payload["sentMessageIdentity"]["localMessageId"] is not None
        assert payload["trace"]["localStoreUpdated"] is True
        assert fake_client.calls == [
            {
                "reference": -100300,
                "text": "Да, пришлю сегодня.\nПроверю финал.",
                "reply_to_message_id": 10,
            }
        ]
        assert fake_history.manual_sent == [(-100300, 501)]
        assert fake_roster.invalidated is True

        async with runtime.session_factory() as session:
            saved = await MessageRepository(session).get_by_chat_and_telegram_message_id(
                chat_id=chat.id,
                telegram_message_id=501,
            )
            assert saved is not None
            assert saved.raw_text == "Да, пришлю сегодня.\nПроверю финал."
            assert saved.reply_to_message_id == source.id

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_new_telegram_message_sender_handles_runtime_only_chat_with_message_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run_assertions() -> None:
        runtime = await _build_runtime(tmp_path, monkeypatch)
        fake_client = _FakeSendClient(runtime_chat_id=-100777, next_message_id=53)
        sender = NewTelegramMessageSender(
            config=_build_config(tmp_path),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
        )

        payload = await sender.send_chat_message(
            build_runtime_only_chat_id(-100777),
            text="Смотрю сейчас.",
            source_message_key="telegram:-100777:41",
            reply_to_source_message_key="telegram:-100777:41",
        )

        assert payload["ok"] is True
        assert payload["chat"]["localChatId"] is None
        assert payload["sentMessage"]["localMessageId"] is None
        assert payload["sentMessage"]["replyToRuntimeMessageId"] == 41
        assert payload["sentMessageIdentity"]["messageKey"] == "telegram:-100777:53"
        assert fake_client.calls[0]["reply_to_message_id"] == 41

        async with runtime.session_factory() as session:
            assert await MessageRepository(session).count_messages() == 0

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_new_telegram_message_sender_rejects_empty_text_without_transport_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run_assertions() -> None:
        runtime = await _build_runtime(tmp_path, monkeypatch)
        fake_client = _FakeSendClient()
        sender = NewTelegramMessageSender(
            config=_build_config(tmp_path),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
        )

        try:
            await sender.send_chat_message(1, text="   ")
        except ValueError as error:
            assert str(error) == "Нельзя отправить пустое сообщение."
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected empty send to fail.")

        assert fake_client.calls == []
        await runtime.dispose()

    asyncio.run(run_assertions())


async def _build_runtime(tmp_path: Path, monkeypatch) -> object:
    database_path = tmp_path / "new-send" / "astra.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    runtime = build_database_runtime(Settings())
    await bootstrap_database(runtime)
    return runtime


def _build_config(tmp_path: Path) -> NewTelegramRuntimeConfig:
    return NewTelegramRuntimeConfig(
        enabled=True,
        session_path=tmp_path / "new-send" / "new-runtime.session",
        device_name="test-device",
        product_surfaces_enabled=True,
    )


class _FakeSendClient:
    def __init__(self, *, runtime_chat_id: int = -100300, next_message_id: int = 501) -> None:
        self.runtime_chat_id = runtime_chat_id
        self.next_message_id = next_message_id
        self.calls: list[dict[str, object]] = []

    async def send_message(
        self,
        reference: int | str,
        *,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> NewTelegramSendResult:
        self.calls.append(
            {
                "reference": reference,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return NewTelegramSendResult(
            chat=NewTelegramChatSummary(
                telegram_chat_id=self.runtime_chat_id,
                title="Runtime chat",
                chat_type="group",
                username="runtime_chat",
            ),
            message=NewTelegramRemoteMessage(
                telegram_message_id=self.next_message_id,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 23, 10, 5, tzinfo=timezone.utc),
                raw_text=text,
                normalized_text=text,
                reply_to_telegram_message_id=reply_to_message_id,
                forward_info=None,
                has_media=False,
                media_type=None,
                entities_json=None,
                source_type="message",
            ),
        )


class _FakeHistory:
    def __init__(self) -> None:
        self.manual_sent: list[tuple[int, int]] = []

    def note_sent_message(self, *, chat, message) -> None:
        self.last_sent = (chat, message)

    def note_manual_send(self, *, runtime_chat_id: int, runtime_message_id: int) -> None:
        self.manual_sent.append((runtime_chat_id, runtime_message_id))


class _FakeRoster:
    def __init__(self) -> None:
        self.invalidated = False

    def invalidate(self) -> None:
        self.invalidated = True
