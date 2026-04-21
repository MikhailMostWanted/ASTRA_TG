import asyncio
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
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
    bot: object
    chat_id: int
    chat: object | None = None
    answers: list[str] | None = None

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=self.chat_id)
        self.answers = []

    async def answer(self, text: str):
        self.answers.append(text)
        return SimpleNamespace(message_id=1000 + len(self.answers))


class FakeBot:
    async def send_message(self, chat_id: int, text: str):
        return SimpleNamespace(chat_id=chat_id, text=text, message_id=1)


def test_reply_examples_rebuild_filters_noise_and_retrieval_prefers_good_local_examples(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-examples" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        builder_module = importlib.import_module("services.reply_examples_builder")
        retriever_module = importlib.import_module("services.reply_examples_retriever")
        formatter_module = importlib.import_module("services.reply_examples_formatter")
        reply_context_module = importlib.import_module("services.reply_context_builder")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory = ChatMemoryRepository(session)
            people_memory = PersonMemoryRepository(session)
            reply_examples = ReplyExampleRepository(session)

            product_chat = await chats.upsert_chat(
                telegram_chat_id=-100410,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            vendor_chat = await chats.upsert_chat(
                telegram_chat_id=-100411,
                title="Клиентский бюджет",
                handle="vendor_ops",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            async def add_message(
                *,
                chat_id: int,
                telegram_message_id: int,
                sender_id: int | None,
                sender_name: str,
                direction: str,
                sent_at: datetime,
                text: str,
            ) -> None:
                await messages.create_message(
                    chat_id=chat_id,
                    telegram_message_id=telegram_message_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    direction=direction,
                    source_adapter="telegram",
                    source_type="message",
                    sent_at=sent_at,
                    raw_text=text,
                    normalized_text=text,
                )

            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
                text="Когда сможешь прислать финальный бюджет?",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 20, 9, 8, tzinfo=timezone.utc),
                text="Да, гляну сейчас и вернусь с апдейтом по бюджету.",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 9, 20, tzinfo=timezone.utc),
                text="+",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=4,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 20, 9, 21, tzinfo=timezone.utc),
                text="ок",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=5,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 9, 30, tzinfo=timezone.utc),
                text="/reply @product_team",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=6,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 20, 9, 31, tzinfo=timezone.utc),
                text="/status",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=7,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                text="Можешь вечером прислать итоговый бюджет?",
            )
            await add_message(
                chat_id=vendor_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 11, 0, tzinfo=timezone.utc),
                text="Когда сможешь прислать файл по бюджету клиента?",
            )
            await add_message(
                chat_id=vendor_chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 20, 11, 9, tzinfo=timezone.utc),
                text="Смотрю это. Вернусь с апдейтом чуть позже.",
            )
            await session.commit()

            rebuild_result = await builder_module.ReplyExamplesBuilder(
                chat_repository=chats,
                message_repository=messages,
                reply_example_repository=reply_examples,
            ).rebuild()
            await session.commit()

            assert rebuild_result.examples_created == 2
            assert rebuild_result.chats_processed == 2
            assert rebuild_result.messages_scanned == 9
            assert await reply_examples.count_examples() == 2
            assert await reply_examples.count_chats_with_examples() == 2

            stored_examples = await reply_examples.list_examples(limit=10)
            assert {example.inbound_text for example in stored_examples} == {
                "Когда сможешь прислать финальный бюджет?",
                "Когда сможешь прислать файл по бюджету клиента?",
            }

            await reply_examples.create_example(
                chat_id=product_chat.id,
                inbound_message_id=None,
                outbound_message_id=None,
                inbound_text="Можешь вечером прислать итоговый бюджет?",
                outbound_text="Ок",
                inbound_normalized="можешь вечером прислать итоговый бюджет",
                outbound_normalized="ок",
                context_before_json=[],
                example_type="request",
                source_person_key="tg:11",
                quality_score=0.12,
            )
            await session.commit()

            context = await reply_context_module.ReplyContextBuilder(
                message_repository=messages,
                chat_memory_repository=chat_memory,
                person_memory_repository=people_memory,
            ).build(product_chat)
            assert not hasattr(context, "code")

            retrieval = await retriever_module.ReplyExamplesRetriever(
                reply_example_repository=reply_examples
            ).retrieve_for_context(context, limit=5)

            assert retrieval.support_used is True
            assert retrieval.match_count == 2
            assert len(retrieval.matches) == 2
            assert retrieval.matches[0].chat_id == product_chat.id
            assert retrieval.matches[0].source_person_key == "tg:11"
            assert retrieval.matches[0].score >= retrieval.matches[1].score
            assert all(match.quality_score >= 0.5 for match in retrieval.matches)

            rendered = formatter_module.ReplyExamplesFormatter().format_matches(
                chat_title=product_chat.title,
                chat_reference="@product_team",
                retrieval_result=retrieval,
            )
            assert "Похожие прошлые ответы" in rendered
            assert "Команда продукта" in rendered
            assert "Сходство:" in rendered
            assert "тот же чат" in rendered.lower()

            status_text = await BotStatusService(
                chats,
                SettingRepository(session),
                SystemRepository(session),
                messages,
                DigestRepository(session),
                chat_memory,
                people_memory,
                StyleProfileRepository(session),
                ChatStyleOverrideRepository(session),
                TaskRepository(session),
                ReminderRepository(session),
                reply_examples,
            ).build_status_message()
            assert "Few-shot layer: готов" in status_text
            assert "Reply examples: 3" in status_text
            assert "Чатов с reply examples: 2" in status_text
            assert "/reply с few-shot support: готов" in status_text

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_commands_use_few_shot_support_and_show_examples(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-examples-commands" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        management_module = importlib.import_module("bot.handlers.management")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            product_chat = await chats.upsert_chat(
                telegram_chat_id=-100420,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            empty_chat = await chats.upsert_chat(
                telegram_chat_id=-100421,
                title="Без примеров",
                handle="no_examples",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            async def add_message(
                *,
                chat_id: int,
                telegram_message_id: int,
                sender_id: int | None,
                sender_name: str,
                direction: str,
                sent_at: datetime,
                text: str,
            ) -> None:
                await messages.create_message(
                    chat_id=chat_id,
                    telegram_message_id=telegram_message_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    direction=direction,
                    source_adapter="telegram",
                    source_type="message",
                    sent_at=sent_at,
                    raw_text=text,
                    normalized_text=text,
                )

            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
                text="Когда сможешь прислать финальный бюджет?",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 20, 9, 8, tzinfo=timezone.utc),
                text="Да, гляну сейчас и вернусь с апдейтом по бюджету.",
            )
            await add_message(
                chat_id=product_chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                text="Можешь вечером прислать итоговый бюджет?",
            )
            await session.commit()

        rebuild_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_examples_rebuild_command(
            rebuild_message,
            SimpleNamespace(args=None),
            runtime.session_factory,
        )
        assert any("Собрано reply examples: 1" in answer for answer in rebuild_message.answers)
        assert any("Чатов: 2" in answer for answer in rebuild_message.answers)
        assert any("Просмотрено сообщений: 3" in answer for answer in rebuild_message.answers)

        preview_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_examples_command(
            preview_message,
            SimpleNamespace(args="@product_team"),
            runtime.session_factory,
        )
        assert any("Похожие прошлые ответы" in answer for answer in preview_message.answers)
        assert any("финальный бюджет" in answer.lower() for answer in preview_message.answers)
        assert any("Сходство:" in answer for answer in preview_message.answers)

        reply_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_command(
            reply_message,
            SimpleNamespace(args="@product_team"),
            runtime.session_factory,
        )
        assert any("Few-shot support: найден" in answer for answer in reply_message.answers)
        assert any("Что сделал few-shot-слой:" in answer for answer in reply_message.answers)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            empty_chat = await chats.find_chat_by_handle_or_telegram_id("@no_examples")
            assert empty_chat is not None

            await messages.create_message(
                chat_id=empty_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
                raw_text="Смотрю это и скоро отвечу.",
                normalized_text="Смотрю это и скоро отвечу.",
            )
            await messages.create_message(
                chat_id=empty_chat.id,
                telegram_message_id=2,
                sender_id=51,
                sender_name="Борис",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 12, 5, tzinfo=timezone.utc),
                raw_text="Кинь потом фото кота.",
                normalized_text="Кинь потом фото кота.",
            )
            await messages.create_message(
                chat_id=empty_chat.id,
                telegram_message_id=3,
                sender_id=51,
                sender_name="Борис",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 12, 6, tzinfo=timezone.utc),
                raw_text="И давай позже обсудим шашлыки.",
                normalized_text="И давай позже обсудим шашлыки.",
            )
            await session.commit()

        no_support_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_command(
            no_support_message,
            SimpleNamespace(args="@no_examples"),
            runtime.session_factory,
        )
        assert any("Few-shot support: не найден" in answer for answer in no_support_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())
