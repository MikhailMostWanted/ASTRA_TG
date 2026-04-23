import asyncio
from datetime import datetime, timezone
from pathlib import Path

from astra_runtime.chat_identity import build_runtime_only_chat_id
from astra_runtime.new_telegram import (
    NewTelegramChatSummary,
    NewTelegramMessageHistory,
    NewTelegramReplyWorkspace,
    NewTelegramRemoteMessage,
    NewTelegramRuntimeConfig,
)
from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, MessageRepository


def test_new_telegram_message_history_builds_snapshot_identity_and_pagination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run_assertions() -> None:
        runtime = await _build_runtime(tmp_path, monkeypatch)
        fake_client = _FakeHistoryClient(
            chat=NewTelegramChatSummary(
                telegram_chat_id=-100300,
                title="Команда продукта",
                chat_type="group",
                username="product_team",
            ),
            messages=(
                _remote_message(
                    101,
                    direction="outbound",
                    sender_id=7,
                    sender_name="Михаил",
                    text="Смотрю и скоро вернусь.",
                ),
                _remote_message(
                    102,
                    direction="inbound",
                    sender_id=11,
                    sender_name="Анна",
                    text="Ок, жду апдейт.",
                ),
                _remote_message(
                    103,
                    direction="outbound",
                    sender_id=7,
                    sender_name="Михаил",
                    text="Понял, сверяю финальную версию.",
                ),
                _remote_message(
                    104,
                    direction="inbound",
                    sender_id=11,
                    sender_name="Анна",
                    text="Когда пришлёшь финальный файл?",
                    reply_to_telegram_message_id=103,
                ),
            ),
        )

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat = await chats.upsert_chat(
                telegram_chat_id=-100300,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            local_first = await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=101,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc),
                raw_text="Смотрю и скоро вернусь.",
                normalized_text="Смотрю и скоро вернусь.",
            )
            local_reply_target = await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=103,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 23, 10, 2, tzinfo=timezone.utc),
                raw_text="Понял, сверяю финальную версию.",
                normalized_text="Понял, сверяю финальную версию.",
            )
            await session.commit()

        history = NewTelegramMessageHistory(
            config=_build_config(tmp_path),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
            snapshot_ttl_seconds=60,
        )

        workspace = await history.get_chat_workspace(chat.id, limit=3)

        assert workspace["chat"]["chatKey"] == "telegram:-100300"
        assert workspace["chat"]["localChatId"] == chat.id
        assert workspace["chat"]["messageCount"] == 3
        assert [message["runtimeMessageId"] for message in workspace["messages"]] == [102, 103, 104]
        assert workspace["messages"][1]["localMessageId"] == local_reply_target.id
        assert workspace["messages"][-1]["localMessageId"] is None
        assert workspace["messages"][-1]["replyToRuntimeMessageId"] == 103
        assert workspace["messages"][-1]["replyToLocalMessageId"] == local_reply_target.id
        assert workspace["messages"][-1]["replyToMessageKey"] == "telegram:-100300:103"
        assert workspace["replyContext"]["available"] is True
        assert workspace["replyContext"]["sourceMessageKey"] == "telegram:-100300:104"
        assert workspace["replyContext"]["draftScopeBasis"]["sourceMessageKey"] == "telegram:-100300:104"
        assert workspace["reply"]["kind"] == "workspace_context_only"
        assert workspace["status"]["source"] == "new"
        assert workspace["status"]["availability"]["historyReadable"] is True
        assert workspace["status"]["availability"]["legacyWorkspaceAvailable"] is True
        assert workspace["status"]["availability"]["sendAvailable"] is False
        assert workspace["status"]["messageSource"]["oldestMessageKey"] == "telegram:-100300:102"
        assert workspace["status"]["messageSource"]["newestMessageKey"] == "telegram:-100300:104"
        assert workspace["history"]["beforeRuntimeMessageId"] == 102
        assert workspace["freshness"]["syncTrigger"] == "runtime_poll"
        assert fake_client.calls == [
            {
                "reference": -100300,
                "limit": 80,
                "min_message_id": None,
                "max_message_id": None,
            }
        ]

        cached_workspace = await history.get_chat_workspace(chat.id, limit=3)
        assert cached_workspace["freshness"]["syncTrigger"] == "runtime_cache"
        assert len(fake_client.calls) == 1

        page = await history.get_chat_messages(
            chat.id,
            limit=2,
            before_runtime_message_id=104,
        )
        assert [message["runtimeMessageId"] for message in page["messages"]] == [102, 103]
        assert page["history"]["returnedCount"] == 2
        assert page["history"]["oldestRuntimeMessageId"] == 102
        assert page["status"]["availability"]["canLoadOlder"] is True
        assert page["messages"][1]["localMessageId"] == local_reply_target.id
        assert local_first.id != local_reply_target.id
        assert len(fake_client.calls) == 2

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_new_telegram_message_history_reads_runtime_only_chat_without_legacy_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run_assertions() -> None:
        runtime = await _build_runtime(tmp_path, monkeypatch)
        fake_client = _FakeHistoryClient(
            chat=NewTelegramChatSummary(
                telegram_chat_id=-100777,
                title="Runtime chat",
                chat_type="group",
                username="runtime_chat",
            ),
            messages=(
                _remote_message(
                    41,
                    direction="inbound",
                    sender_id=11,
                    sender_name="Анна",
                    text="Сможешь посмотреть это сегодня?",
                ),
                _remote_message(
                    52,
                    direction="outbound",
                    sender_id=7,
                    sender_name="Михаил",
                    text="Да, беру в работу.",
                    reply_to_telegram_message_id=41,
                ),
            ),
        )
        history = NewTelegramMessageHistory(
            config=_build_config(tmp_path),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
            snapshot_ttl_seconds=60,
        )

        workspace = await history.get_chat_workspace(
            build_runtime_only_chat_id(-100777),
            limit=2,
        )

        assert workspace["chat"]["id"] < 0
        assert workspace["chat"]["localChatId"] is None
        assert workspace["chat"]["chatKey"] == "telegram:-100777"
        assert workspace["chat"]["workspaceAvailable"] is False
        assert workspace["status"]["availability"]["workspaceAvailable"] is True
        assert workspace["status"]["availability"]["legacyWorkspaceAvailable"] is False
        assert workspace["status"]["messageSource"]["backend"] == "new_runtime"
        assert workspace["messages"][0]["chatId"] == build_runtime_only_chat_id(-100777)
        assert workspace["messages"][0]["localMessageId"] is None
        assert workspace["replyContext"]["available"] is True
        assert workspace["replyContext"]["sourceMessageKey"] == "telegram:-100777:41"
        assert workspace["reply"]["actions"]["send"] is False

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_new_telegram_reply_workspace_builds_reply_from_same_runtime_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run_assertions() -> None:
        runtime = await _build_runtime(tmp_path, monkeypatch)
        fake_client = _FakeHistoryClient(
            chat=NewTelegramChatSummary(
                telegram_chat_id=-100888,
                title="Runtime reply",
                chat_type="group",
                username="runtime_reply",
            ),
            messages=(
                _remote_message(
                    41,
                    direction="inbound",
                    sender_id=11,
                    sender_name="Анна",
                    text="Сможешь посмотреть это сегодня?",
                ),
                _remote_message(
                    52,
                    direction="outbound",
                    sender_id=7,
                    sender_name="Михаил",
                    text="Да, смотрю сейчас.",
                    reply_to_telegram_message_id=41,
                ),
                _remote_message(
                    53,
                    direction="inbound",
                    sender_id=11,
                    sender_name="Анна",
                    text="Если что, дай короткий апдейт.",
                ),
            ),
        )
        history = NewTelegramMessageHistory(
            config=_build_config(tmp_path),
            session_factory=runtime.session_factory,
            client_factory=lambda _config: fake_client,
            snapshot_ttl_seconds=60,
        )
        reply_workspace = NewTelegramReplyWorkspace(
            settings=Settings(),
            session_factory=runtime.session_factory,
            history=history,
        )

        workspace = await history.get_chat_workspace(
            build_runtime_only_chat_id(-100888),
            limit=3,
        )
        reply_payload, reply_context = await reply_workspace.build_preview_from_workspace(workspace)

        assert reply_payload["kind"] == "suggestion"
        assert reply_payload["suggestion"] is not None
        assert reply_context["available"] is True
        assert reply_payload["suggestion"]["trigger"]["messageKey"] == reply_context["sourceMessageKey"]
        assert reply_payload["suggestion"]["focus"]["label"] == reply_context["focusLabel"]
        assert reply_payload["suggestion"]["opportunity"]["mode"] == reply_context["replyOpportunityMode"]
        assert reply_payload["suggestion"]["sourceBackend"] == "new_runtime"
        assert reply_payload["suggestion"]["trigger"]["messageKey"] in {
            message["messageKey"] for message in workspace["messages"]
        }

        await runtime.dispose()

    asyncio.run(run_assertions())


async def _build_runtime(tmp_path: Path, monkeypatch) -> object:
    database_path = tmp_path / "new-history" / "astra.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    runtime = build_database_runtime(Settings())
    await bootstrap_database(runtime)
    return runtime


def _build_config(tmp_path: Path) -> NewTelegramRuntimeConfig:
    session_path = tmp_path / "new-history" / "new-runtime.session"
    return NewTelegramRuntimeConfig(
        enabled=True,
        session_path=session_path,
        device_name="test-device",
        asset_session_files=(session_path,),
        product_surfaces_enabled=True,
    )


def _remote_message(
    telegram_message_id: int,
    *,
    direction: str,
    sender_id: int,
    sender_name: str,
    text: str,
    reply_to_telegram_message_id: int | None = None,
) -> NewTelegramRemoteMessage:
    return NewTelegramRemoteMessage(
        telegram_message_id=telegram_message_id,
        sender_id=sender_id,
        sender_name=sender_name,
        direction=direction,
        sent_at=datetime(2026, 4, 23, 10, telegram_message_id % 60, tzinfo=timezone.utc),
        raw_text=text,
        normalized_text=text,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
        forward_info=None,
        has_media=False,
        media_type=None,
        entities_json=None,
        source_type="message",
    )


class _FakeHistoryClient:
    def __init__(
        self,
        *,
        chat: NewTelegramChatSummary,
        messages: tuple[NewTelegramRemoteMessage, ...],
    ) -> None:
        self.chat = chat
        self.messages = messages
        self.calls: list[dict[str, int | str | None]] = []

    async def fetch_history(
        self,
        reference: int | str,
        *,
        limit: int,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
    ) -> tuple[NewTelegramChatSummary, tuple[NewTelegramRemoteMessage, ...]]:
        self.calls.append(
            {
                "reference": reference,
                "limit": limit,
                "min_message_id": min_message_id,
                "max_message_id": max_message_id,
            }
        )
        filtered = [
            message
            for message in self.messages
            if (min_message_id is None or message.telegram_message_id > min_message_id)
            and (max_message_id is None or message.telegram_message_id < max_message_id)
        ]
        return self.chat, tuple(filtered[-limit:])
