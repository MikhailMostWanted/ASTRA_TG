import asyncio
import importlib
import importlib.util
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatRepository,
    DigestRepository,
    MessageRepository,
    SettingRepository,
)
from services.providers.models import ProviderExecutionResult, ProviderStatus


def _load_digest_module(name: str):
    assert importlib.util.find_spec(name) is not None, f"Модуль {name} ещё не реализован"
    return importlib.import_module(name)


def _build_digest_service(*, messages, digests, settings):
    digest_engine_module = _load_digest_module("services.digest_engine")
    digest_builder_module = _load_digest_module("services.digest_builder")
    digest_formatter_module = _load_digest_module("services.digest_formatter")

    return digest_engine_module.DigestEngineService(
        message_repository=messages,
        digest_repository=digests,
        setting_repository=settings,
        builder=digest_builder_module.DigestBuilder(),
        formatter=digest_formatter_module.DigestFormatter(),
    )


@dataclass(slots=True)
class FakeSentMessage:
    chat_id: int
    text: str
    message_id: int


@dataclass(slots=True)
class FakeBot:
    sent_messages: list[FakeSentMessage]

    def __init__(self) -> None:
        self.sent_messages = []

    async def send_message(self, chat_id: int, text: str):
        sent_message = FakeSentMessage(
            chat_id=chat_id,
            text=text,
            message_id=len(self.sent_messages) + 1,
        )
        self.sent_messages.append(sent_message)
        return SimpleNamespace(message_id=sent_message.message_id)


@dataclass(slots=True)
class FakeIncomingMessage:
    bot: FakeBot
    chat_id: int
    chat: object | None = None
    answers: list[str] | None = None

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=self.chat_id)
        self.answers = []

    async def answer(self, text: str):
        self.answers.append(text)
        return SimpleNamespace(message_id=1000 + len(self.answers))


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

    async def improve_digest(self, request):
        return ProviderExecutionResult.failure("API сейчас недоступен.")


def test_digest_engine_builds_and_saves_digest_from_messages(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "digest-build" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            digests = DigestRepository(session)
            repo_settings = SettingRepository(session)

            source_news = await chats.upsert_chat(
                telegram_chat_id=-100100,
                title="Новости релизов",
                handle="release_news",
                chat_type="channel",
                is_enabled=True,
            )
            source_team = await chats.upsert_chat(
                telegram_chat_id=-100200,
                title="Команда продукта",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=source_news.id,
                telegram_message_id=1,
                sender_name="Редакция",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 7, 0, tzinfo=timezone.utc),
                raw_text="Ок",
                normalized_text="Ок",
            )
            await messages.create_message(
                chat_id=source_news.id,
                telegram_message_id=2,
                sender_name="Редакция",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 30, tzinfo=timezone.utc),
                raw_text="Деплой на staging завершён, проверяем отчёты по конверсии и отклики пользователей.",
                normalized_text="Деплой на staging завершён, проверяем отчёты по конверсии и отклики пользователей.",
            )
            await messages.create_message(
                chat_id=source_news.id,
                telegram_message_id=3,
                sender_name="Редакция",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 35, tzinfo=timezone.utc),
                raw_text="Деплой на staging завершён, проверяем отчёты по конверсии и отклики пользователей.",
                normalized_text="Деплой на staging завершён, проверяем отчёты по конверсии и отклики пользователей.",
            )
            await messages.create_message(
                chat_id=source_team.id,
                telegram_message_id=4,
                sender_name="Михаил",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 15, tzinfo=timezone.utc),
                raw_text="Собрали feedback по MVP digest: нужен ручной запуск и понятный preview перед публикацией.",
                normalized_text="Собрали feedback по MVP digest: нужен ручной запуск и понятный preview перед публикацией.",
            )
            await session.commit()

            service = _build_digest_service(
                messages=messages,
                digests=digests,
                settings=repo_settings,
            )
            plan = await service.build_manual_digest(
                None,
                now=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            )

            assert plan.has_digest is True
            assert plan.digest_id is not None
            assert plan.message_count == 4
            assert plan.source_count == 2
            assert plan.preview_chunks
            assert "Digest Astra AFT" in plan.preview_chunks[0]
            assert "Новости релизов" in plan.preview_chunks[0]
            assert "Команда продукта" in plan.preview_chunks[0]
            assert "07:00 Редакция: Ок" not in plan.preview_chunks[0]
            assert plan.preview_chunks[0].count("Деплой на staging завершён") == 1

            saved_digest = await digests.get_last_digest()
            assert saved_digest is not None
            assert saved_digest.id == plan.digest_id
            assert saved_digest.summary_short
            assert saved_digest.summary_long
            assert len(saved_digest.items) == 2

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_digest_engine_skips_disabled_and_excluded_sources(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "digest-filtering" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            digests = DigestRepository(session)
            repo_settings = SettingRepository(session)

            active_chat = await chats.upsert_chat(
                telegram_chat_id=-100300,
                title="Активный источник",
                chat_type="group",
                is_enabled=True,
            )
            disabled_chat = await chats.upsert_chat(
                telegram_chat_id=-100301,
                title="Выключенный источник",
                chat_type="group",
                is_enabled=False,
            )
            excluded_chat = await chats.upsert_chat(
                telegram_chat_id=-100302,
                title="Без digest",
                chat_type="channel",
                is_enabled=True,
                exclude_from_digest=True,
            )
            await session.commit()

            for index, chat in enumerate((active_chat, disabled_chat, excluded_chat), start=1):
                await messages.create_message(
                    chat_id=chat.id,
                    telegram_message_id=index,
                    sender_name="Тест",
                    direction="inbound",
                    source_adapter="telegram",
                    source_type="message",
                    sent_at=datetime(2026, 4, 20, 8 + index, 0, tzinfo=timezone.utc),
                    raw_text=f"Содержательное сообщение {index} для проверки digest.",
                    normalized_text=f"Содержательное сообщение {index} для проверки digest.",
                )
            await session.commit()

            service = _build_digest_service(
                messages=messages,
                digests=digests,
                settings=repo_settings,
            )
            plan = await service.build_manual_digest(
                "24h",
                now=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            )

            assert plan.has_digest is True
            assert plan.preview_chunks
            digest_text = "\n".join(plan.preview_chunks)
            assert "Активный источник" in digest_text
            assert "Выключенный источник" not in digest_text
            assert "Без digest" not in digest_text

            saved_digest = await digests.get_last_digest()
            assert saved_digest is not None
            assert [item.title for item in saved_digest.items] == ["Активный источник"]

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_digest_llm_handler_falls_back_to_deterministic_digest_when_provider_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "digest-llm-fallback" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL_FAST", "test-fast")
        monkeypatch.setenv("LLM_MODEL_DEEP", "test-deep")
        monkeypatch.setenv("LLM_REFINE_DIGEST_ENABLED", "true")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)
        recent_message_at = datetime.now(timezone.utc) - timedelta(hours=1)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100400,
                title="Новости релизов",
                handle="release_news",
                chat_type="channel",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=1,
                sender_name="Редакция",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=recent_message_at,
                raw_text="Деплой на staging завершён, проверяем отчёты по конверсии и отклики пользователей.",
                normalized_text="Деплой на staging завершён, проверяем отчёты по конверсии и отклики пользователей.",
            )
            await session.commit()

        management_module = importlib.import_module("bot.handlers.management")
        monkeypatch.setattr(
            management_module,
            "_build_provider_manager",
            lambda: FakeUnavailableProviderManager(),
        )

        fake_bot = FakeBot()
        fake_message = FakeIncomingMessage(bot=fake_bot, chat_id=901)
        await management_module.handle_digest_llm_command(
            fake_message,
            SimpleNamespace(args="24h"),
            runtime.session_factory,
        )

        assert fake_bot.sent_messages
        assert any("Digest Astra AFT" in sent.text for sent in fake_bot.sent_messages)
        assert any("Новости релизов" in sent.text for sent in fake_bot.sent_messages)
        assert any("API сейчас недоступен" in answer for answer in fake_message.answers)
        assert any("детерминированный digest" in answer.lower() for answer in fake_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_digest_engine_handles_empty_window_without_saving_digest(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "digest-empty" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            digests = DigestRepository(session)
            repo_settings = SettingRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100400,
                title="Старые сообщения",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=1,
                sender_name="Тест",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
                raw_text="Это сообщение слишком старое для окна.",
                normalized_text="Это сообщение слишком старое для окна.",
            )
            await session.commit()

            service = _build_digest_service(
                messages=messages,
                digests=digests,
                settings=repo_settings,
            )
            plan = await service.build_manual_digest(
                "12h",
                now=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            )

            assert plan.has_digest is False
            assert plan.preview_chunks == [
                "За 12h по активным digest-источникам сообщений не найдено."
            ]
            assert await digests.count_digests() == 0

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_digest_now_handler_runs_happy_path(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "digest-handler" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)
        recent_message_at = datetime.now(timezone.utc) - timedelta(hours=1)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            repo_settings = SettingRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100500,
                title="Ручной digest",
                handle="manual_digest",
                chat_type="channel",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=1,
                sender_name="Редакция",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=recent_message_at,
                raw_text="Подготовили первый реальный digest MVP без LLM и с локальной эвристикой ранжирования.",
                normalized_text="Подготовили первый реальный digest MVP без LLM и с локальной эвристикой ранжирования.",
            )
            await repo_settings.set_value(key="digest.target.chat_id", value_text="-100900")
            await repo_settings.set_value(key="digest.target.label", value_text="@digest_target")
            await repo_settings.set_value(key="digest.target.type", value_text="channel")
            await session.commit()

        management_module = importlib.import_module("bot.handlers.management")
        assert hasattr(management_module, "handle_digest_now_command")

        fake_bot = FakeBot()
        fake_message = FakeIncomingMessage(bot=fake_bot, chat_id=777)
        command = SimpleNamespace(args="24h")

        await management_module.handle_digest_now_command(
            fake_message,
            command,
            runtime.session_factory,
        )

        assert len(fake_bot.sent_messages) >= 2
        assert fake_bot.sent_messages[0].chat_id == 777
        assert any(sent.chat_id == -100900 for sent in fake_bot.sent_messages)
        assert any("отправлен" in answer.lower() for answer in fake_message.answers)

        async with runtime.session_factory() as session:
            digests = DigestRepository(session)
            saved_digest = await digests.get_last_digest()
            assert saved_digest is not None
            assert saved_digest.delivered_to_chat_id == -100900
            assert saved_digest.delivered_message_id == 2

        await runtime.dispose()

    asyncio.run(run_assertions())
