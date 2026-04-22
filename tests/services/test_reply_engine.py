import asyncio
import importlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    MessageRepository,
    PersonMemoryRepository,
    SettingRepository,
    StyleProfileRepository,
)
from services.providers.models import (
    ProviderExecutionResult,
    ProviderStatus,
    ReplyRefinementCandidate,
)


@dataclass(slots=True)
class FakeIncomingMessage:
    bot: object
    chat_id: int
    chat: object = field(init=False)
    answers: list[str] = field(default_factory=list)
    reply_markups: list[object | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=self.chat_id)

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(text)
        self.reply_markups.append(reply_markup)
        return SimpleNamespace(message_id=1000 + len(self.answers))


class FakeBot:
    async def send_message(self, chat_id: int, text: str):
        return SimpleNamespace(chat_id=chat_id, text=text, message_id=1)


class FakeUnavailableProviderManager:
    async def get_status(self, *, check_api: bool = False):
        return ProviderStatus(
            enabled=True,
            configured=False,
            provider_name="openai_compatible",
            model_fast="test-fast",
            model_deep="test-deep",
            timeout_seconds=15.0,
            available=False,
            reason="API сейчас недоступен.",
            reply_refine_enabled=True,
            digest_refine_enabled=True,
            reply_refine_available=False,
            digest_refine_available=False,
            api_checked=check_api,
        )

    async def rewrite_reply(self, request):
        return ProviderExecutionResult.failure("API сейчас недоступен.")


class FakeRejectingProviderManager(FakeUnavailableProviderManager):
    async def get_status(self, *, check_api: bool = False):
        return ProviderStatus(
            enabled=True,
            configured=True,
            provider_name="openai_compatible",
            model_fast="test-fast",
            model_deep="test-deep",
            timeout_seconds=15.0,
            available=True,
            reason="API сконфигурирован.",
            reply_refine_enabled=True,
            digest_refine_enabled=True,
            reply_refine_available=True,
            digest_refine_available=True,
            api_checked=check_api,
        )

    async def rewrite_reply(self, request):
        return ProviderExecutionResult.success(
            ReplyRefinementCandidate(
                messages=(
                    "В данном случае благодарю за терпение, завтра утром отправлю файл на 25 страниц!!!",
                ),
                raw_text="В данном случае благодарю за терпение, завтра утром отправлю файл на 25 страниц!!!",
                model_name="test-fast",
            ),
            provider_name="openai_compatible",
        )


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
            style_adapter_module = importlib.import_module("services.style_adapter")
            style_selector_module = importlib.import_module("services.style_selector")
            persona_adapter_module = importlib.import_module("services.persona_adapter")
            persona_core_module = importlib.import_module("services.persona_core")
            persona_guardrails_module = importlib.import_module("services.persona_guardrails")

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
                style_selector=style_selector_module.StyleSelectorService(
                    style_profile_repository=StyleProfileRepository(session),
                    chat_style_override_repository=ChatStyleOverrideRepository(session),
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                style_adapter=style_adapter_module.StyleAdapter(),
                persona_core_service=persona_core_module.PersonaCoreService(
                    SettingRepository(session)
                ),
                persona_adapter=persona_adapter_module.PersonaAdapter(),
                persona_guardrails=persona_guardrails_module.PersonaGuardrails(),
            )
            formatter = reply_formatter_module.ReplyFormatter()

            result = await service.build_reply("@product_team")

            assert result.kind == "suggestion"
            assert result.suggestion is not None
            assert result.suggestion.chat_id == team_chat.id
            assert result.suggestion.source_message_id == 3
            assert result.suggestion.base_reply_text
            assert result.suggestion.reply_messages
            assert len(result.suggestion.reply_messages) >= 2
            assert result.suggestion.final_reply_messages
            assert len(result.suggestion.final_reply_messages) >= 2
            assert result.suggestion.style_profile_key == "friend_explain"
            assert result.suggestion.style_notes
            assert result.suggestion.persona_applied is True
            assert result.suggestion.persona_notes
            assert result.suggestion.guardrail_flags == ()
            assert result.suggestion.reply_text
            assert "бюджет" in result.suggestion.reply_text.lower()
            assert result.suggestion.final_reply_messages[0].startswith(
                ("ну", "а", "да", "не", "это", "я")
            )
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
            assert "💬 Ответ / Команда продукта" in rendered
            assert "Фокус ответа" in rendered
            assert "[OK] Почему выбран:" in rendered
            assert "Анна" in rendered
            assert "[OK] Стиль: friend_explain" in rendered
            assert "[OK] Персона: да" in rendered
            assert "Готовый вариант ответа" in rendered
            assert "1." in rendered
            assert "Почему именно так" in rendered
            assert "[OK] Ограничители: без замечаний" in rendered
            assert "Риск:" in rendered
            assert "уверенность" in rendered

        management_module = importlib.import_module("bot.handlers.management")
        fake_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_command(
            fake_message,
            SimpleNamespace(args="@product_team"),
            runtime.session_factory,
        )
        assert any("Команда продукта" in answer for answer in fake_message.answers)
        assert any("[OK] Стиль: friend_explain" in answer for answer in fake_message.answers)
        assert any("[OK] Персона: да" in answer for answer in fake_message.answers)
        assert any("Фокус ответа" in answer for answer in fake_message.answers)
        assert any("Готовый вариант ответа" in answer for answer in fake_message.answers)
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
        style_adapter_module = importlib.import_module("services.style_adapter")
        style_selector_module = importlib.import_module("services.style_selector")
        persona_adapter_module = importlib.import_module("services.persona_adapter")
        persona_core_module = importlib.import_module("services.persona_core")
        persona_guardrails_module = importlib.import_module("services.persona_guardrails")
        formatter = reply_formatter_module.ReplyFormatter()

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)
            settings_repo = SettingRepository(session)
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
                style_selector=style_selector_module.StyleSelectorService(
                    style_profile_repository=StyleProfileRepository(session),
                    chat_style_override_repository=ChatStyleOverrideRepository(session),
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                style_adapter=style_adapter_module.StyleAdapter(),
                persona_core_service=persona_core_module.PersonaCoreService(settings_repo),
                persona_adapter=persona_adapter_module.PersonaAdapter(),
                persona_guardrails=persona_guardrails_module.PersonaGuardrails(),
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
            resolved_outbound_chat = await chats.upsert_chat(
                telegram_chat_id=-100304,
                title="Тема уже закрыта моим сообщением",
                handle="self_closed",
                chat_type="group",
                is_enabled=True,
            )
            persona_disabled_chat = await chats.upsert_chat(
                telegram_chat_id=-100303,
                title="Persona выключен",
                handle="persona_off",
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
                telegram_message_id=0,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 1, tzinfo=timezone.utc),
                raw_text="Смотрю и скоро вернусь.",
                normalized_text="Смотрю и скоро вернусь.",
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
            await messages.create_message(
                chat_id=resolved_outbound_chat.id,
                telegram_message_id=0,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 14, tzinfo=timezone.utc),
                raw_text="Поймал, сейчас посмотрю.",
                normalized_text="Поймал, сейчас посмотрю.",
            )
            await messages.create_message(
                chat_id=resolved_outbound_chat.id,
                telegram_message_id=1,
                sender_id=25,
                sender_name="Саша",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 16, tzinfo=timezone.utc),
                raw_text="Скинь итоговый файл, пожалуйста.",
                normalized_text="Скинь итоговый файл, пожалуйста.",
            )
            await messages.create_message(
                chat_id=resolved_outbound_chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 18, tzinfo=timezone.utc),
                raw_text="Файл уже отправил тебе в почту.",
                normalized_text="Файл уже отправил тебе в почту.",
            )
            await messages.create_message(
                chat_id=persona_disabled_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 20, tzinfo=timezone.utc),
                raw_text="Смотрю это и скоро вернусь.",
                normalized_text="Смотрю это и скоро вернусь.",
            )
            await messages.create_message(
                chat_id=persona_disabled_chat.id,
                telegram_message_id=2,
                sender_id=18,
                sender_name="Ира",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 22, tzinfo=timezone.utc),
                raw_text="Ок, жду апдейт.",
                normalized_text="Ок, жду апдейт.",
            )
            await messages.create_message(
                chat_id=persona_disabled_chat.id,
                telegram_message_id=3,
                sender_id=18,
                sender_name="Ира",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 26, tzinfo=timezone.utc),
                raw_text="Когда сможешь написать по срокам?",
                normalized_text="Когда сможешь написать по срокам?",
            )
            await session.commit()

            too_short = await service.build_reply("@too_short")
            assert too_short.kind == "not_enough_data"
            assert "мало" in formatter.format_result(too_short).lower()

            self_last = await service.build_reply("@self_last")
            assert self_last.kind == "suggestion"
            assert self_last.suggestion is not None
            assert self_last.suggestion.reply_opportunity_mode == "follow_up_after_self"
            self_last_reason = self_last.suggestion.reply_opportunity_reason.lower()
            assert any(
                marker in self_last_reason
                for marker in ("follow-up", "обещание вернуться", "уместен")
            )
            assert self_last.suggestion.strategy != "не отвечать"

            self_closed = await service.build_reply("@self_closed")
            assert self_closed.kind == "suggestion"
            assert self_closed.suggestion is not None
            assert self_closed.suggestion.reply_opportunity_mode == "hold"
            assert self_closed.suggestion.strategy == "не отвечать"
            assert "явного незакрытого повода" in self_closed.suggestion.reply_opportunity_reason.lower()

            await settings_repo.set_value(
                key="persona.enabled",
                value_json={"enabled": False},
            )
            await session.commit()

            persona_off = await service.build_reply("@persona_off")
            assert persona_off.kind == "suggestion"
            assert persona_off.suggestion is not None
            assert persona_off.suggestion.persona_applied is False
            assert persona_off.suggestion.final_reply_messages == persona_off.suggestion.reply_messages
            assert "[OFF] Персона: нет" in formatter.format_result(persona_off)

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_context_prefers_latest_meaningful_trigger_over_low_signal_tail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-focus-fresh-context" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        reply_context_module = importlib.import_module("services.reply_context_builder")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)

            chat = await chats.upsert_chat(
                telegram_chat_id=-100555,
                title="Свежий хвост",
                handle="fresh_tail",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
                raw_text="Смотрю задачу.",
                normalized_text="Смотрю задачу.",
            )
            meaningful = await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=2,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 2, tzinfo=timezone.utc),
                raw_text="Когда сможешь прислать финальный файл?",
                normalized_text="Когда сможешь прислать финальный файл?",
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 3, tzinfo=timezone.utc),
                raw_text="ок",
                normalized_text="ок",
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=4,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 4, tzinfo=timezone.utc),
                raw_text="?",
                normalized_text="?",
            )
            await session.commit()

            context = await reply_context_module.ReplyContextBuilder(
                message_repository=messages,
                chat_memory_repository=chat_memory_repo,
                person_memory_repository=person_memory_repo,
            ).build(chat)

            assert not isinstance(context, reply_context_module.ReplyContextIssue)
            assert context.target_message.id == meaningful.id
            assert context.focus_label == "вопрос"
            assert "сигнал слабее" in context.focus_reason.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_context_demotes_short_reaction_trigger_in_favor_of_real_question(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-focus-short-reaction" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        reply_context_module = importlib.import_module("services.reply_context_builder")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)

            chat = await chats.upsert_chat(
                telegram_chat_id=-100556,
                title="Короткая реакция",
                handle="short_reaction",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                raw_text="Смотрю задачу.",
                normalized_text="Смотрю задачу.",
            )
            meaningful = await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=2,
                sender_id=11,
                sender_name="Настенька💗",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 2, tzinfo=timezone.utc),
                raw_text="Когда сможешь прислать финальный файл?",
                normalized_text="Когда сможешь прислать финальный файл?",
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Настенька💗",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 3, tzinfo=timezone.utc),
                raw_text="Красиво слаженно",
                normalized_text="Красиво слаженно",
            )
            await session.commit()

            context = await reply_context_module.ReplyContextBuilder(
                message_repository=messages,
                chat_memory_repository=chat_memory_repo,
                person_memory_repository=person_memory_repo,
            ).build(chat)

            assert not isinstance(context, reply_context_module.ReplyContextIssue)
            assert context.target_message.id == meaningful.id
            assert context.focus_label == "вопрос"
            assert "слабый сигнал" in context.focus_reason.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_llm_handler_falls_back_to_deterministic_reply_when_provider_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-llm-fallback" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL_FAST", "test-fast")
        monkeypatch.setenv("LLM_MODEL_DEEP", "test-deep")
        monkeypatch.setenv("LLM_REFINE_REPLY_ENABLED", "true")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)

            team_chat = await chats.upsert_chat(
                telegram_chat_id=-100310,
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
                linked_people_json=[{"person_key": "tg:11", "display_name": "Анна", "message_count": 1}],
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
                interaction_pattern="регулярно выходит на связь; обычно пишет коротко, часто задаёт вопросы.",
            )
            await session.commit()

        management_module = importlib.import_module("bot.handlers.management")
        monkeypatch.setattr(
            management_module,
            "_build_provider_manager",
            lambda: FakeUnavailableProviderManager(),
        )

        fake_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_llm_command(
            fake_message,
            SimpleNamespace(args="@product_team"),
            runtime.session_factory,
        )

        assert any("Команда продукта" in answer for answer in fake_message.answers)
        assert any("[WARN] LLM: резервный режим" in answer for answer in fake_message.answers)
        assert any("API сейчас недоступен" in answer for answer in fake_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_engine_keeps_rejected_llm_candidate_and_guardrail_reason(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-llm-guardrails" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)
            settings_repo = SettingRepository(session)

            team_chat = await chats.upsert_chat(
                telegram_chat_id=-100311,
                title="Команда продукта",
                handle="product_team_llm",
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
                raw_text="Когда сможешь скинуть финальный файл по бюджету?",
                normalized_text="Когда сможешь скинуть финальный файл по бюджету?",
            )
            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 6, tzinfo=timezone.utc),
                raw_text="ок",
                normalized_text="ок",
            )
            await chat_memory_repo.upsert_chat_memory(
                chat_id=team_chat.id,
                chat_summary_short="Анна ждёт файл по бюджету.",
                chat_summary_long="Есть открытый хвост по файлу и срокам.",
                current_state="спокойное рабочее обсуждение, есть открытые хвосты",
                dominant_topics_json=[{"topic": "бюджет", "mentions": 2}],
                recent_conflicts_json=[],
                pending_tasks_json=["Отправить финальный файл по бюджету."],
                linked_people_json=[{"person_key": "tg:11", "display_name": "Анна", "message_count": 2}],
                last_digest_at=None,
            )
            await person_memory_repo.upsert_person_memory(
                person_key="tg:11",
                display_name="Анна",
                relationship_label="контакт",
                importance_score=84.0,
                last_summary="Ждёт финальный файл по бюджету.",
                known_facts_json=["Ждёт финальный файл по бюджету."],
                sensitive_topics_json=[],
                open_loops_json=["Ждёт финальный файл по бюджету."],
                interaction_pattern="регулярно выходит на связь; обычно пишет коротко, часто задаёт вопросы.",
            )
            await session.commit()

            reply_engine_module = importlib.import_module("services.reply_engine")
            reply_context_module = importlib.import_module("services.reply_context_builder")
            reply_classifier_module = importlib.import_module("services.reply_classifier")
            reply_strategy_module = importlib.import_module("services.reply_strategy")
            style_adapter_module = importlib.import_module("services.style_adapter")
            style_selector_module = importlib.import_module("services.style_selector")
            persona_adapter_module = importlib.import_module("services.persona_adapter")
            persona_core_module = importlib.import_module("services.persona_core")
            persona_guardrails_module = importlib.import_module("services.persona_guardrails")
            reply_refiner_module = importlib.import_module("services.providers.reply_refiner")

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
                style_selector=style_selector_module.StyleSelectorService(
                    style_profile_repository=StyleProfileRepository(session),
                    chat_style_override_repository=ChatStyleOverrideRepository(session),
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                style_adapter=style_adapter_module.StyleAdapter(),
                persona_core_service=persona_core_module.PersonaCoreService(settings_repo),
                persona_adapter=persona_adapter_module.PersonaAdapter(),
                persona_guardrails=persona_guardrails_module.PersonaGuardrails(),
                reply_refiner=reply_refiner_module.ReplyLLMRefiner(
                    provider_manager=FakeRejectingProviderManager()
                ),
            )

            result = await service.build_reply("@product_team_llm", use_provider_refinement=True)

            assert result.kind == "suggestion"
            assert result.suggestion is not None
            assert result.suggestion.llm_refine_requested is True
            assert result.suggestion.llm_refine_applied is False
            assert result.suggestion.llm_refine_raw_candidate is not None
            assert "благодарю за терпение" in result.suggestion.llm_refine_raw_candidate.lower()
            assert result.suggestion.llm_refine_baseline_messages
            assert result.suggestion.llm_refine_decision_reason is not None
            assert result.suggestion.llm_refine_decision_reason.source == "guardrails"
            assert "guardrails" in result.suggestion.llm_refine_decision_reason.summary.lower()
            assert "слишком_литературно" in result.suggestion.llm_refine_decision_reason.flags
            assert result.suggestion.reply_text == "\n".join(result.suggestion.final_reply_messages)
            assert "благодарю за терпение" not in result.suggestion.reply_text.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_engine_prefers_question_over_later_low_signal_message(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-focus-selection" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        reply_engine_module = importlib.import_module("services.reply_engine")
        reply_context_module = importlib.import_module("services.reply_context_builder")
        reply_classifier_module = importlib.import_module("services.reply_classifier")
        reply_strategy_module = importlib.import_module("services.reply_strategy")
        style_adapter_module = importlib.import_module("services.style_adapter")
        style_selector_module = importlib.import_module("services.style_selector")
        persona_adapter_module = importlib.import_module("services.persona_adapter")
        persona_core_module = importlib.import_module("services.persona_core")
        persona_guardrails_module = importlib.import_module("services.persona_guardrails")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)
            settings_repo = SettingRepository(session)

            focus_chat = await chats.upsert_chat(
                telegram_chat_id=-100320,
                title="Фокус на вопросе",
                handle="focus_question",
                chat_type="group",
                is_enabled=True,
            )
            day_chat = await chats.upsert_chat(
                telegram_chat_id=-100321,
                title="Разговор про день",
                handle="day_question",
                chat_type="group",
                is_enabled=True,
            )
            no_trigger_chat = await chats.upsert_chat(
                telegram_chat_id=-100322,
                title="Нет триггера",
                handle="no_trigger",
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
                chat_id=focus_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 22, 8, 0, tzinfo=timezone.utc),
                text="Я в дороге, чуть позже отпишусь.",
            )
            await add_message(
                chat_id=focus_chat.id,
                telegram_message_id=2,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 8, 4, tzinfo=timezone.utc),
                text="Когда сможешь прислать файл по бюджету?",
            )
            await add_message(
                chat_id=focus_chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 8, 5, tzinfo=timezone.utc),
                text="хорошо",
            )

            await add_message(
                chat_id=day_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc),
                text="Привет.",
            )
            await add_message(
                chat_id=day_chat.id,
                telegram_message_id=2,
                sender_id=15,
                sender_name="Мария",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 9, 2, tzinfo=timezone.utc),
                text="Как прошел твой день?",
            )
            await add_message(
                chat_id=day_chat.id,
                telegram_message_id=3,
                sender_id=15,
                sender_name="Мария",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 9, 3, tzinfo=timezone.utc),
                text="хорошо",
            )

            await add_message(
                chat_id=no_trigger_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
                text="Я потом вернусь.",
            )
            await add_message(
                chat_id=no_trigger_chat.id,
                telegram_message_id=2,
                sender_id=17,
                sender_name="Игорь",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 10, 1, tzinfo=timezone.utc),
                text="ок",
            )
            await add_message(
                chat_id=no_trigger_chat.id,
                telegram_message_id=3,
                sender_id=17,
                sender_name="Игорь",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 10, 2, tzinfo=timezone.utc),
                text="+",
            )
            await session.commit()

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
                style_selector=style_selector_module.StyleSelectorService(
                    style_profile_repository=StyleProfileRepository(session),
                    chat_style_override_repository=ChatStyleOverrideRepository(session),
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                style_adapter=style_adapter_module.StyleAdapter(),
                persona_core_service=persona_core_module.PersonaCoreService(settings_repo),
                persona_adapter=persona_adapter_module.PersonaAdapter(),
                persona_guardrails=persona_guardrails_module.PersonaGuardrails(),
            )

            focus_result = await service.build_reply("@focus_question")
            assert focus_result.kind == "suggestion"
            assert focus_result.suggestion is not None
            assert focus_result.suggestion.source_message_preview.endswith(
                "Когда сможешь прислать файл по бюджету?"
            )
            assert focus_result.suggestion.focus_label == "вопрос"
            assert "слабый сигнал" in focus_result.suggestion.focus_reason.lower()
            assert focus_result.suggestion.strategy != "не отвечать"

            day_result = await service.build_reply("@day_question")
            assert day_result.kind == "suggestion"
            assert day_result.suggestion is not None
            assert day_result.suggestion.source_message_preview.endswith("Как прошел твой день?")
            assert day_result.suggestion.focus_label == "вопрос"

            no_trigger_result = await service.build_reply("@no_trigger")
            assert no_trigger_result.kind == "suggestion"
            assert no_trigger_result.suggestion is not None
            assert no_trigger_result.suggestion.focus_label == "низкий сигнал"
            assert no_trigger_result.suggestion.strategy == "не отвечать"
            assert no_trigger_result.suggestion.alternative_action is not None

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_engine_relabels_generic_focus_when_strategy_is_no_reply(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-focus-consistency" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        reply_engine_module = importlib.import_module("services.reply_engine")
        reply_context_module = importlib.import_module("services.reply_context_builder")
        reply_classifier_module = importlib.import_module("services.reply_classifier")
        reply_strategy_module = importlib.import_module("services.reply_strategy")
        style_adapter_module = importlib.import_module("services.style_adapter")
        style_selector_module = importlib.import_module("services.style_selector")
        persona_adapter_module = importlib.import_module("services.persona_adapter")
        persona_core_module = importlib.import_module("services.persona_core")
        persona_guardrails_module = importlib.import_module("services.persona_guardrails")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)
            settings_repo = SettingRepository(session)

            chat = await chats.upsert_chat(
                telegram_chat_id=-100323,
                title="Консистентность reply",
                handle="focus_consistency",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_id=19,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc),
                raw_text="По бюджету тогда идём по старой схеме.",
                normalized_text="По бюджету тогда идём по старой схеме.",
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 11, 2, tzinfo=timezone.utc),
                raw_text="Готово, уже добавил это в таблицу.",
                normalized_text="Готово, уже добавил это в таблицу.",
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=3,
                sender_id=19,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 11, 3, tzinfo=timezone.utc),
                raw_text="ок",
                normalized_text="ок",
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=4,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 11, 4, tzinfo=timezone.utc),
                raw_text="Готово, уже добавил это в таблицу.",
                normalized_text="Готово, уже добавил это в таблицу.",
            )
            await session.commit()

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
                style_selector=style_selector_module.StyleSelectorService(
                    style_profile_repository=StyleProfileRepository(session),
                    chat_style_override_repository=ChatStyleOverrideRepository(session),
                    chat_memory_repository=chat_memory_repo,
                    person_memory_repository=person_memory_repo,
                ),
                style_adapter=style_adapter_module.StyleAdapter(),
                persona_core_service=persona_core_module.PersonaCoreService(settings_repo),
                persona_adapter=persona_adapter_module.PersonaAdapter(),
                persona_guardrails=persona_guardrails_module.PersonaGuardrails(),
            )

            result = await service.build_reply("@focus_consistency")

            assert result.kind == "suggestion"
            assert result.suggestion is not None
            assert result.suggestion.strategy == "не отвечать"
            assert result.suggestion.focus_label == "слабый триггер"
            assert "не видно явного вопроса" in result.suggestion.focus_reason.lower()
            assert "явного незакрытого повода" in result.suggestion.reason_short.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_reply_command_without_reference_opens_reply_picker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reply-picker-command" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)

            focused_chat = await chats.upsert_chat(
                telegram_chat_id=-100330,
                title="Команда клиента",
                handle="client_room",
                chat_type="group",
                is_enabled=True,
            )
            noisy_chat = await chats.upsert_chat(
                telegram_chat_id=-100331,
                title="Фоновый чат",
                handle="noise_room",
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
                chat_id=focused_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc),
                text="Собираю апдейт.",
            )
            await add_message(
                chat_id=focused_chat.id,
                telegram_message_id=2,
                sender_id=21,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 11, 2, tzinfo=timezone.utc),
                text="Когда будет короткий статус по клиенту?",
            )
            await add_message(
                chat_id=focused_chat.id,
                telegram_message_id=3,
                sender_id=21,
                sender_name="Анна",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 11, 3, tzinfo=timezone.utc),
                text="ок",
            )
            await chat_memory_repo.upsert_chat_memory(
                chat_id=focused_chat.id,
                chat_summary_short="Ждут короткий статус по клиенту.",
                chat_summary_long="Чат про клиентский статус с ожидаемым апдейтом.",
                current_state="Нужно вернуться с коротким статусом.",
                dominant_topics_json=[{"topic": "клиент", "mentions": 2}],
                recent_conflicts_json=[],
                pending_tasks_json=["Вернуть статус по клиенту."],
                linked_people_json=[],
                last_digest_at=None,
            )

            await add_message(
                chat_id=noisy_chat.id,
                telegram_message_id=1,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                sent_at=datetime(2026, 4, 22, 11, 10, tzinfo=timezone.utc),
                text="Потом вернусь.",
            )
            await add_message(
                chat_id=noisy_chat.id,
                telegram_message_id=2,
                sender_id=31,
                sender_name="Игорь",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 11, 11, tzinfo=timezone.utc),
                text="ага",
            )
            await add_message(
                chat_id=noisy_chat.id,
                telegram_message_id=3,
                sender_id=31,
                sender_name="Игорь",
                direction="inbound",
                sent_at=datetime(2026, 4, 22, 11, 12, tzinfo=timezone.utc),
                text="+",
            )
            await session.commit()

        management_module = importlib.import_module("bot.handlers.management")
        picker_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_reply_command(
            picker_message,
            SimpleNamespace(args=None),
            runtime.session_factory,
        )

        assert len(picker_message.answers) == 1
        assert "💬 Выбери чат" in picker_message.answers[0]
        assert "незакрытым триггером" in picker_message.answers[0]
        assert "фокус вопрос" in picker_message.answers[0]
        assert picker_message.reply_markups[0] is not None
        first_row = picker_message.reply_markups[0].inline_keyboard[0]
        assert [button.text for button in first_row] == ["Команда клиента"]

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
