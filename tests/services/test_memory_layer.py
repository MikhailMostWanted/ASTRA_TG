import asyncio
import importlib
import importlib.util
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from services.status_summary import BotStatusService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
)


def _load_module(name: str):
    assert importlib.util.find_spec(name) is not None, f"Модуль {name} ещё не реализован"
    return importlib.import_module(name)


def _build_memory_service(*, chats, messages, digests, settings, chat_memory, people_memory):
    memory_builder_module = _load_module("services.memory_builder")
    chat_memory_builder_module = _load_module("services.chat_memory_builder")
    people_memory_builder_module = _load_module("services.people_memory_builder")
    memory_formatter_module = _load_module("services.memory_formatter")

    return memory_builder_module.MemoryService(
        chat_repository=chats,
        message_repository=messages,
        digest_repository=digests,
        setting_repository=settings,
        chat_memory_repository=chat_memory,
        person_memory_repository=people_memory,
        chat_builder=chat_memory_builder_module.ChatMemoryBuilder(),
        people_builder=people_memory_builder_module.PeopleMemoryBuilder(),
        formatter=memory_formatter_module.MemoryFormatter(),
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


def test_memory_rebuild_builds_chat_and_people_memory_from_local_messages(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "memory-build" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            repositories_module = importlib.import_module("storage.repositories")
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            digests = DigestRepository(session)
            repo_settings = SettingRepository(session)
            system = SystemRepository(session)
            chat_memory_repo = repositories_module.ChatMemoryRepository(session)
            people_memory_repo = repositories_module.PersonMemoryRepository(session)

            team_chat = await chats.upsert_chat(
                telegram_chat_id=-100100,
                title="Проект Альфа",
                handle="alpha_team",
                chat_type="group",
                is_enabled=True,
            )
            anna_chat = await chats.upsert_chat(
                telegram_chat_id=501,
                title="Анна",
                handle="anna_pm",
                chat_type="private",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=1,
                sender_id=1,
                sender_name="Михаил",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
                raw_text="Нужно проверить релиз и обновить отчёты по конверсии.",
                normalized_text="Нужно проверить релиз и обновить отчёты по конверсии.",
            )
            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=2,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 15, tzinfo=timezone.utc),
                raw_text="Я завтра скину финальный файл по бюджету.",
                normalized_text="Я завтра скину финальный файл по бюджету.",
            )
            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=3,
                sender_id=22,
                sender_name="Игорь",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 9, 40, tzinfo=timezone.utc),
                raw_text="Почему опять сломался импорт? Это срочно!",
                normalized_text="Почему опять сломался импорт? Это срочно!",
            )
            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=4,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 5, tzinfo=timezone.utc),
                raw_text="Созвонимся после обеда?",
                normalized_text="Созвонимся после обеда?",
            )
            await messages.create_message(
                chat_id=anna_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 11, 0, tzinfo=timezone.utc),
                raw_text="Вечером отправлю документы по страховке.",
                normalized_text="Вечером отправлю документы по страховке.",
            )
            await messages.create_message(
                chat_id=anna_chat.id,
                telegram_message_id=2,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 11, 20, tzinfo=timezone.utc),
                raw_text="Напомни завтра про врача.",
                normalized_text="Напомни завтра про врача.",
            )
            await digests.create_digest(
                chat_id=None,
                window_start=datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
                summary_short="Сводка по проекту",
                summary_long="Подробная сводка по проекту",
                items=[
                    {
                        "source_chat_id": team_chat.id,
                        "source_message_id": None,
                        "title": "Проект Альфа",
                        "summary": "Есть активное обсуждение релиза.",
                        "sort_order": 1,
                    }
                ],
            )
            await session.commit()

            service = _build_memory_service(
                chats=chats,
                messages=messages,
                digests=digests,
                settings=repo_settings,
                chat_memory=chat_memory_repo,
                people_memory=people_memory_repo,
            )
            rebuild_result = await service.rebuild()
            await session.commit()

            assert rebuild_result.updated_chat_count == 2
            assert rebuild_result.updated_people_count == 3
            assert rebuild_result.analyzed_message_count == 6

            team_memory = await chat_memory_repo.get_chat_memory(team_chat.id)
            assert team_memory is not None
            assert team_memory.chat_summary_short
            assert team_memory.chat_summary_long
            assert team_memory.current_state
            assert team_memory.last_digest_at is not None
            assert any("релиз" in str(item).lower() for item in (team_memory.dominant_topics_json or []))
            assert any("Анна" in str(item) for item in (team_memory.linked_people_json or []))
            assert any("скину" in str(item).lower() or "созвонимся" in str(item).lower() for item in (team_memory.pending_tasks_json or []))
            assert any("срочно" in str(item).lower() or "сломался" in str(item).lower() for item in (team_memory.recent_conflicts_json or []))

            anna_memory = await people_memory_repo.get_person_memory("tg:11")
            assert anna_memory is not None
            assert anna_memory.display_name == "Анна"
            assert anna_memory.relationship_label == "контакт"
            assert anna_memory.importance_score > 0
            assert anna_memory.last_summary
            assert anna_memory.interaction_pattern
            assert any("Проект Альфа" in str(item) or "Анна" in str(item) for item in (anna_memory.known_facts_json or []))
            assert any("страх" in str(item).lower() or "врач" in str(item).lower() for item in (anna_memory.sensitive_topics_json or []))
            assert any("отправлю" in str(item).lower() or "напомни" in str(item).lower() for item in (anna_memory.open_loops_json or []))

            status_service = BotStatusService(
                chat_repository=chats,
                setting_repository=repo_settings,
                system_repository=system,
                message_repository=messages,
                digest_repository=digests,
                chat_memory_repository=chat_memory_repo,
                person_memory_repository=people_memory_repo,
                style_profile_repository=StyleProfileRepository(session),
                chat_style_override_repository=ChatStyleOverrideRepository(session),
            )
            status_text = await status_service.build_status_message()
            assert "Memory-карт чатов: 2" in status_text
            assert "Memory-карт людей: 3" in status_text
            assert "Reply layer: готов" in status_text
            assert "Чатов с данными для reply: 1" in status_text
            assert "Опора reply на memory: да" in status_text
            assert "Последний rebuild memory:" in status_text
            assert "Данных для memory: да" in status_text

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_memory_handlers_render_cards_and_support_single_source_rebuild(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "memory-handlers" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            team_chat = await chats.upsert_chat(
                telegram_chat_id=-100200,
                title="Команда релиза",
                handle="release_team",
                chat_type="group",
                is_enabled=True,
            )
            await chats.upsert_chat(
                telegram_chat_id=-100201,
                title="Архивный чат",
                handle="archive_team",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=team_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 13, 0, tzinfo=timezone.utc),
                raw_text="Завтра скину обновлённый план релиза.",
                normalized_text="Завтра скину обновлённый план релиза.",
            )
            await session.commit()

        management_module = importlib.import_module("bot.handlers.management")
        assert hasattr(management_module, "handle_memory_rebuild_command")
        assert hasattr(management_module, "handle_chat_memory_command")
        assert hasattr(management_module, "handle_person_memory_command")

        fake_message = FakeIncomingMessage(bot=FakeBot(), chat_id=777)

        await management_module.handle_memory_rebuild_command(
            fake_message,
            SimpleNamespace(args="@release_team"),
            runtime.session_factory,
        )
        assert any("Чатов обновлено: 1" in answer for answer in fake_message.answers)
        assert any("Карточек людей обновлено: 1" in answer for answer in fake_message.answers)

        fake_message.answers.clear()
        await management_module.handle_chat_memory_command(
            fake_message,
            SimpleNamespace(args="@release_team"),
            runtime.session_factory,
        )
        assert any("Команда релиза" in answer for answer in fake_message.answers)
        assert any("Доминирующие темы" in answer for answer in fake_message.answers)

        fake_message.answers.clear()
        await management_module.handle_person_memory_command(
            fake_message,
            SimpleNamespace(args="Анна"),
            runtime.session_factory,
        )
        assert any("Анна" in answer for answer in fake_message.answers)
        assert any("Открытые хвосты" in answer for answer in fake_message.answers)

        fake_message.answers.clear()
        await management_module.handle_chat_memory_command(
            fake_message,
            SimpleNamespace(args=None),
            runtime.session_factory,
        )
        assert any("/chat_memory <chat_id|@username>" in answer for answer in fake_message.answers)

        fake_message.answers.clear()
        await management_module.handle_person_memory_command(
            fake_message,
            SimpleNamespace(args="@missing"),
            runtime.session_factory,
        )
        assert any("ещё не собрана" in answer.lower() or "не найдена" in answer.lower() for answer in fake_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())
