import asyncio
import importlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    PersonMemoryRepository,
    StyleProfileRepository,
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


def test_style_selector_and_adapter_support_builtin_profiles_and_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "style-layer" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        style_selector_module = importlib.import_module("services.style_selector")
        style_adapter_module = importlib.import_module("services.style_adapter")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)
            style_profile_repo = StyleProfileRepository(session)
            override_repo = ChatStyleOverrideRepository(session)

            explain_chat = await chats.upsert_chat(
                telegram_chat_id=-100410,
                title="Разбор задач",
                handle="explain_chat",
                chat_type="group",
                is_enabled=True,
            )
            romantic_chat = await chats.upsert_chat(
                telegram_chat_id=501001,
                title="Личный чат",
                handle="romantic_chat",
                chat_type="private",
                is_enabled=True,
            )
            await session.commit()

            await chat_memory_repo.upsert_chat_memory(
                chat_id=explain_chat.id,
                chat_summary_short="Тут часто разбирают детали по шагам.",
                chat_summary_long="Общение спокойное, много объяснений и упрощений без конфликтов.",
                current_state="спокойный объясняющий разбор по шагам",
                dominant_topics_json=[{"topic": "задачи", "mentions": 4}],
                recent_conflicts_json=[],
                pending_tasks_json=[],
                linked_people_json=[{"person_key": "tg:22", "display_name": "Саша", "message_count": 6}],
                last_digest_at=None,
            )
            await person_memory_repo.upsert_person_memory(
                person_key="tg:22",
                display_name="Саша",
                relationship_label="друг",
                importance_score=65.0,
                last_summary="Любит, когда мысль раскладывают коротко и по шагам.",
                known_facts_json=["Часто просит пояснить, что именно имеется в виду."],
                sensitive_topics_json=[],
                open_loops_json=[],
                interaction_pattern="часто просит объяснить проще и по шагам, без длинных абзацев.",
            )
            await chat_memory_repo.upsert_chat_memory(
                chat_id=romantic_chat.id,
                chat_summary_short="Тёплый личный чат.",
                chat_summary_long="Много мягких реплик, близкий романтический контекст и нежность.",
                current_state="мягкий личный разговор, явный романтический контекст и нежность",
                dominant_topics_json=[{"topic": "личное", "mentions": 5}],
                recent_conflicts_json=[],
                pending_tasks_json=[],
                linked_people_json=[],
                last_digest_at=None,
            )
            await session.commit()

            profiles = await style_profile_repo.list_profiles()
            assert [profile.key for profile in profiles] == [
                "base",
                "friend_hard",
                "friend_explain",
                "practical_short",
                "romantic_soft",
                "tension_soft",
            ]

            selector = style_selector_module.StyleSelectorService(
                style_profile_repository=style_profile_repo,
                chat_style_override_repository=override_repo,
                chat_memory_repository=chat_memory_repo,
                person_memory_repository=person_memory_repo,
            )

            explain_selection = await selector.select_for_chat(explain_chat)
            assert explain_selection.profile.key == "friend_explain"
            assert explain_selection.source == "fallback"
            assert "объяс" in explain_selection.source_reason.lower()

            romantic_selection = await selector.select_for_chat(romantic_chat)
            assert romantic_selection.profile.key == "romantic_soft"
            assert romantic_selection.source == "fallback"
            assert "романтичес" in romantic_selection.source_reason.lower()

            practical_profile = await style_profile_repo.get_by_key("practical_short")
            assert practical_profile is not None
            await override_repo.set_override(
                chat_id=explain_chat.id,
                style_profile_id=practical_profile.id,
            )
            await session.commit()

            override_selection = await selector.select_for_chat(explain_chat)
            assert override_selection.profile.key == "practical_short"
            assert override_selection.source == "override"

            removed = await override_repo.unset_override(chat_id=explain_chat.id)
            await session.commit()
            assert removed is True
            assert await override_repo.count_overrides() == 0

            adapter = style_adapter_module.StyleAdapter()
            adapted = adapter.adapt(
                draft_text=(
                    "Понял. Смотрю это сейчас, проверю детали и вернусь с конкретным "
                    "апдейтом чуть позже!"
                ),
                profile=explain_selection.profile,
                strategy="мягко ответить",
            )
            assert len(adapted.messages) >= 2
            assert len(adapted.messages) <= explain_selection.profile.max_message_count
            assert "!" not in "\n".join(adapted.messages)
            assert sum(len(message) for message in adapted.messages) <= len(
                "Понял. Смотрю это сейчас, проверю детали и вернусь с конкретным апдейтом чуть позже!"
            )
            assert adapted.messages[0] == adapted.messages[0].lower()
            assert adapted.notes

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_style_management_commands_show_profiles_and_chat_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "style-management" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        management_module = importlib.import_module("bot.handlers.management")

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            person_memory_repo = PersonMemoryRepository(session)

            explain_chat = await chats.upsert_chat(
                telegram_chat_id=-100411,
                title="Диалог по проекту",
                handle="project_style",
                chat_type="group",
                is_enabled=True,
            )
            await chat_memory_repo.upsert_chat_memory(
                chat_id=explain_chat.id,
                chat_summary_short="Часто идёт спокойное объяснение по задачам.",
                chat_summary_long="Много пояснений и упрощений, без жёстких конфликтов.",
                current_state="спокойный объясняющий диалог",
                dominant_topics_json=[{"topic": "проект", "mentions": 3}],
                recent_conflicts_json=[],
                pending_tasks_json=[],
                linked_people_json=[{"person_key": "tg:44", "display_name": "Илья", "message_count": 5}],
                last_digest_at=None,
            )
            await person_memory_repo.upsert_person_memory(
                person_key="tg:44",
                display_name="Илья",
                relationship_label="друг",
                importance_score=60.0,
                last_summary="Любит короткие пояснения без воды.",
                known_facts_json=["Часто просит разложить мысль по шагам."],
                sensitive_topics_json=[],
                open_loops_json=[],
                interaction_pattern="обычно просит объяснить проще и покороче.",
            )
            await session.commit()

        profiles_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_style_profiles_command(
            profiles_message,
            runtime.session_factory,
        )
        assert any("Доступные style-профили" in answer for answer in profiles_message.answers)
        assert any("friend_explain" in answer for answer in profiles_message.answers)
        assert any("romantic_soft" in answer for answer in profiles_message.answers)

        set_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_style_set_command(
            set_message,
            SimpleNamespace(args="@project_style practical_short"),
            runtime.session_factory,
        )
        assert any("Ручной override: practical_short" in answer for answer in set_message.answers)
        assert any("Источник профиля: ручной override" in answer for answer in set_message.answers)

        status_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_style_status_command(
            status_message,
            SimpleNamespace(args="@project_style"),
            runtime.session_factory,
        )
        assert any("Эффективный профиль: practical_short" in answer for answer in status_message.answers)
        assert any("Ручной override: practical_short" in answer for answer in status_message.answers)

        unset_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_style_unset_command(
            unset_message,
            SimpleNamespace(args="@project_style"),
            runtime.session_factory,
        )
        assert any("Ручной override снят" in answer for answer in unset_message.answers)

        fallback_status = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_style_status_command(
            fallback_status,
            SimpleNamespace(args="@project_style"),
            runtime.session_factory,
        )
        assert any("Ручной override: не задан" in answer for answer in fallback_status.answers)
        assert any("Эффективный профиль: friend_explain" in answer for answer in fallback_status.answers)
        assert any("Источник профиля: автовыбор" in answer for answer in fallback_status.answers)

        missing_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_style_status_command(
            missing_message,
            SimpleNamespace(args="@missing_chat"),
            runtime.session_factory,
        )
        assert any("не зарегистрирован в allowlist" in answer.lower() for answer in missing_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())
