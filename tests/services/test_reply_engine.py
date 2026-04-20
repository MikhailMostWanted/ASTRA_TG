import asyncio
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    MessageRepository,
    PersonMemoryRepository,
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


def test_reply_engine_builds_local_draft_and_formats_handler_response(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-engine" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)

            team_chat = await chats.upsert_chat(
                telegram_chat_id=-100300,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
                raw_text="Смотрю бюджет и вернусь чуть позже.",
                normalized_text="Смотрю бюджет и вернусь чуть позже.",
            )
            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=2,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 5, tzinfo=timezone.utc),
                raw_text="Ок, тогда жду апдейт по бюджету.",
                normalized_text="Ок, тогда жду апдейт по бюджету.",
            )
            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 25, tzinfo=timezone.utc),
                raw_text="Когда сможешь скинуть финальный файл по бюджету?",
                normalized_text="Когда сможешь скинуть финальный файл по бюджету?",
            )
            await chat_memory_repo.upsert_chat_memory(
                chat_id=team_chat.id,
                chat_summary_short="Идёт спокойное обсуждение бюджета и финального файла.",
                chat_summary_long="Анна ждёт апдейт по бюджету, вопрос пока остаётся открытым.",
                current_state="спокойное рабочее обсуждение, есть открытые хвосты",
                dominant_topics_json=[{"topic": "бюджет", "mentions": 3}],
                recent_conflicts_json=[],
                pending_tasks_json=["09:25 Анна: Когда сможешь скинуть финальный файл по бюджету?"],
                linked_people_json=[{"person_key": "tg:11", "display_name": "Анна", "message_count": 2}],
                last_digest_at=None,
            )
            await person_memory_repo.upsert_person_memory(
                person_key="tg:11",
                display_name="Анна",
                relationship_label="контакт",
                importance_score=84.0,
                last_summary="Регулярно пишет по бюджету и ждёт апдейты без лишней драмы.",
                known_facts_json=["Ждёт финальный файл по бюджету."],
                sensitive_topics_json=["деньги и бюджет: бюджет"],
                open_loops_json=["Ждёт финальный файл по бюджету."],
                interaction_pattern="регулярно выходит на связь; чаще встречается в группах; обычно пишет коротко, часто задаёт вопросы.",
            )
            await session.commit()

            reply_engine_module = importlib.import_module("services.reply_engine")
            reply_context_module = importlib.import_module("services.reply_context_builder")
            reply_classifier_module = importlib.import_module("services.reply_classifier")
            reply_strategy_module = importlib.import_module("services.reply_strategy")
            reply_formatter_module = importlib.import_module("services.reply_formatter")

            service = reply_engine_module.ReplyEngineService(
                chat_repository=chats,
                message_repository=messages,
                chat_memory_repository=chat_memory_repo,
                person_memory_repository=person_memory_repo,
                context_builder=reply_context_module.ReplyContextBuilder(
                    message_repository=messages,
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                classifier=reply_classifier_module.ReplyClassifier(),
                strategy_resolver=reply_strategy_module.ReplyStrategyResolver(),
            )
            formatter = reply_formatter_module.ReplyFormatter()

            result = await service.build_reply("@product_team")

            assert result.kind == "suggestion"
            assert result.suggestion is not None
            assert result.suggestion.chat_id == team_chat.id
            assert result.suggestion.source_message_id == 3
            assert result.suggestion.reply_text
            assert "бюджет" in result.suggestion.reply_text.lower()
            assert result.suggestion.reason_short
            assert result.suggestion.risk_label in {"низкий", "средний", "высокий", "лучше не отвечать"}
            assert 0.0 < result.suggestion.confidence <= 1.0
            assert result.suggestion.strategy in {
                "уточнить",
                "поддержать",
                "мягко ответить",
                "снять напряжение",
                "отложить",
                "поставить границу",
                "не отвечать",
            }

            rendered = formatter.format_result(result)
            assert "Чат: Команда продукта" in rendered
            assert "Ориентир: Анна" in rendered
            assert "Черновик" in rendered
            assert "Риск:" in rendered
            assert "Уверенность:" in rendered

        management_module = importlib.import_module("bot.handlers.management")
        fake_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_command(
            fake_message,
            SimpleNamespace(args="@product_team"),
            runtime.session_factory,
        )
        assert any("Команда продукта" in answer for answer in fake_message.answers)
        assert any("Черновик" in answer for answer in fake_message.answers)
        assert any("Риск:" in answer for answer in fake_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_engine_handles_missing_chat_insufficient_context_and_latest_outbound(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-edge-cases" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        reply_engine_module = importlib.import_module("services.reply_engine")
        reply_context_module = importlib.import_module("services.reply_context_builder")
        reply_classifier_module = importlib.import_module("services.reply_classifier")
        reply_strategy_module = importlib.import_module("services.reply_strategy")
        reply_formatter_module = importlib.import_module("services.reply_formatter")
        formatter = reply_formatter_module.ReplyFormatter()

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)
            service = reply_engine_module.ReplyEngineService(
                chat_repository=chats,
                message_repository=messages,
                chat_memory_repository=chat_memory_repo,
                person_memory_repository=person_memory_repo,
                context_builder=reply_context_module.ReplyContextBuilder(
                    message_repository=messages,
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                classifier=reply_classifier_module.ReplyClassifier(),
                strategy_resolver=reply_strategy_module.ReplyStrategyResolver(),
            )

            missing = await service.build_reply("@missing")
            assert missing.kind == "not_found"
            assert "не найден" in formatter.format_result(missing).lower()

            short_chat = await chats.upsert_chat(
                telegram_chat_id=-100301,
                title="Мало данных",
                handle="too_short",
                chat_type="group",
                is_enabled=True,
            )
            outbound_chat = await chats.upsert_chat(
                telegram_chat_id=-100302,
                title="Последний ответ уже мой",
                handle="self_last",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=short_chat.id,
                telegram_message_id=1,
                sender_id=15,
                sender_name="Олег",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
                raw_text="Привет",
                normalized_text="Привет",
            )
            await messages.create_message(
                chat_id=outbound_chat.id,
                telegram_message_id=1,
                sender_id=16,
                sender_name="Катя",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 5, tzinfo=timezone.utc),
                raw_text="Скинь, пожалуйста, итоговый файл.",
                normalized_text="Скинь, пожалуйста, итоговый файл.",
            )
            await messages.create_message(
                chat_id=outbound_chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 15, tzinfo=timezone.utc),
                raw_text="Да, вечером скину.",
                normalized_text="Да, вечером скину.",
            )
            await session.commit()

            too_short = await service.build_reply("@too_short")
            assert too_short.kind == "not_enough_data"
            assert "мало" in formatter.format_result(too_short).lower()

            self_last = await service.build_reply("@self_last")
            assert self_last.kind == "latest_is_self"
            assert "уже от тебя" in formatter.format_result(self_last).lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_classifier_covers_basic_situations() -> None:
    reply_classifier_module = importlib.import_module("services.reply_classifier")
    classifier = reply_classifier_module.ReplyClassifier()

    question = classifier.classify_text(
        text="Когда сможешь прислать файл?",
        chat_state="спокойное рабочее обсуждение",
        interaction_pattern="регулярно выходит на связь",
        has_open_loops=True,
    )
    assert question.situation == "question"

    request = classifier.classify_text(
        text="Посмотри, пожалуйста, этот отчёт и дай апдейт.",
        chat_state="спокойное рабочее обсуждение",
        interaction_pattern="обычно пишет коротко",
        has_open_loops=False,
    )
    assert request.situation == "request"

    tension = classifier.classify_text(
        text="Почему опять всё сломалось? Это срочно!",
        chat_state="есть напряжённые сигналы",
        interaction_pattern="обычно пишет коротко",
        has_open_loops=True,
    )
    assert tension.situation == "tension"

    no_reply = classifier.classify_text(
        text="Ок, спасибо",
        chat_state="спокойное рабочее обсуждение",
        interaction_pattern="обычно пишет коротко",
        has_open_loops=False,
    )
    assert no_reply.situation == "no_reply"
