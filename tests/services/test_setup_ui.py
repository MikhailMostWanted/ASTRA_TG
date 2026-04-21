import asyncio
import importlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from services.operational_state import OperationalStateService
from services.setup_ui import SetupUIService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReplyExampleRepository,
    ReminderRepository,
    SettingRepository,
    TaskRepository,
)


@dataclass(slots=True)
class FakeAnswer:
    text: str
    reply_markup: object | None = None


@dataclass(slots=True)
class FakeSentMessage:
    chat_id: int
    text: str
    message_id: int


@dataclass(slots=True)
class FakeBot:
    sent_messages: list[FakeSentMessage] = field(default_factory=list)

    async def send_message(self, chat_id: int, text: str):
        sent = FakeSentMessage(
            chat_id=chat_id,
            text=text,
            message_id=len(self.sent_messages) + 1,
        )
        self.sent_messages.append(sent)
        return SimpleNamespace(message_id=sent.message_id)


@dataclass(slots=True)
class FakeEditableMessage:
    bot: FakeBot
    chat_id: int
    chat_type: str = "private"
    answers: list[FakeAnswer] = field(default_factory=list)
    edits: list[FakeAnswer] = field(default_factory=list)
    chat: object = field(init=False)

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=self.chat_id, type=self.chat_type)

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(FakeAnswer(text=text, reply_markup=reply_markup))
        return SimpleNamespace(message_id=1000 + len(self.answers))

    async def edit_text(self, text: str, reply_markup=None):
        self.edits.append(FakeAnswer(text=text, reply_markup=reply_markup))
        return SimpleNamespace(message_id=2000 + len(self.edits))


@dataclass(slots=True)
class FakeCallback:
    data: str
    message: FakeEditableMessage
    bot: FakeBot
    answers: list[tuple[str | None, bool]] = field(default_factory=list)

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answers.append((text, show_alert))


def test_setup_command_renders_home_screen_and_saves_owner_chat(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-home" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        setup_module = importlib.import_module("bot.handlers.setup")
        message = FakeEditableMessage(bot=FakeBot(), chat_id=701001)
        await setup_module.handle_setup_command(message, runtime.session_factory)

        assert len(message.answers) == 1
        answer = message.answers[0]
        assert "Astra AFT / Setup" in answer.text
        assert "Следующий шаг" in answer.text
        assert answer.reply_markup is not None
        assert {"Статус", "Чеклист", "Диагностика", "Источники", "Дайджест", "Память", "Ответы", "Напоминания", "Обновить"}.issubset(
            set(_keyboard_texts(answer.reply_markup))
        )

        async with runtime.session_factory() as session:
            owner_chat_id = await SettingRepository(session).get_value("bot.owner_chat_id")
            assert owner_chat_id == "701001"

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_start_command_shows_begin_setup_button_for_cold_start(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "start-cold" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        start_module = importlib.import_module("bot.handlers.start")
        message = FakeEditableMessage(bot=FakeBot(), chat_id=701002)
        await start_module.handle_start_command(message, runtime.session_factory)

        assert len(message.answers) == 1
        answer = message.answers[0]
        assert "/setup" in answer.text
        assert answer.reply_markup is not None
        assert _keyboard_texts(answer.reply_markup)[0] == "Начать настройку"

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_start_command_shows_control_center_button_when_system_has_progress(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "start-progress" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat = await chats.upsert_chat(
                telegram_chat_id=-100701,
                title="Продуктовая команда",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
                raw_text="Есть первый контекст.",
                normalized_text="Есть первый контекст.",
            )
            await session.commit()

        start_module = importlib.import_module("bot.handlers.start")
        message = FakeEditableMessage(bot=FakeBot(), chat_id=701003)
        await start_module.handle_start_command(message, runtime.session_factory)

        assert len(message.answers) == 1
        answer = message.answers[0]
        assert answer.reply_markup is not None
        assert _keyboard_texts(answer.reply_markup)[0] == "Открыть центр управления"

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_setup_callback_navigation_renders_section_and_utility_row(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-callback" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        setup_module = importlib.import_module("bot.handlers.setup")
        message = FakeEditableMessage(bot=FakeBot(), chat_id=701004)
        callback = FakeCallback(data="ux:sources", message=message, bot=message.bot)
        await setup_module.handle_setup_callback(callback, runtime.session_factory)

        assert len(message.edits) == 1
        edit = message.edits[0]
        assert "Astra AFT / Sources" in edit.text
        assert edit.reply_markup is not None
        assert {"Назад", "Домой", "Обновить", "Как добавить"}.issubset(
            set(_keyboard_texts(edit.reply_markup))
        )
        assert callback.answers == [(None, False)]

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_memory_rebuild_callback_runs_existing_service(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-memory-action" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat = await chats.upsert_chat(
                telegram_chat_id=-100702,
                title="Команда релиза",
                handle="release_team",
                chat_type="group",
                is_enabled=True,
            )
            for message_id, text in (
                (1, "Соберите обновление по релизу."),
                (2, "Я отвечу после созвона."),
                (3, "Напомни завтра про договор."),
            ):
                await messages.create_message(
                    chat_id=chat.id,
                    telegram_message_id=message_id,
                    sender_id=11,
                    sender_name="Анна",
                    direction="inbound",
                    source_adapter="telegram",
                    source_type="message",
                    sent_at=datetime(2026, 4, 21, 10, message_id, tzinfo=timezone.utc),
                    raw_text=text,
                    normalized_text=text,
                )
            await session.commit()

        setup_module = importlib.import_module("bot.handlers.setup")
        message = FakeEditableMessage(bot=FakeBot(), chat_id=701005)
        callback = FakeCallback(data="ux:memory:rebuild", message=message, bot=message.bot)
        await setup_module.handle_setup_callback(callback, runtime.session_factory)

        assert any("Пересборка памяти завершена." in answer.text for answer in message.answers)
        assert len(message.edits) == 1
        assert "Astra AFT / Memory" in message.edits[0].text

        async with runtime.session_factory() as session:
            assert await ChatMemoryRepository(session).count_chat_memory() > 0
            assert await PersonMemoryRepository(session).count_people_memory() > 0

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_setup_ui_overview_reflects_ready_state(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-overview-ready" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            settings_repo = SettingRepository(session)
            chat_memory = ChatMemoryRepository(session)
            people_memory = PersonMemoryRepository(session)
            reply_examples = ReplyExampleRepository(session)
            tasks = TaskRepository(session)
            reminders = ReminderRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100703,
                title="Операционный чат",
                handle="ops_ready",
                chat_type="group",
                is_enabled=True,
            )
            digest_chat = await chats.upsert_chat(
                telegram_chat_id=-100704,
                title="Digest канал",
                handle="ops_digest",
                chat_type="channel",
                is_enabled=True,
            )
            await session.commit()

            for message_id, text in (
                (1, "Соберите финальный статус по клиенту."),
                (2, "Я отвечу после созвона."),
                (3, "Напомни завтра про договор."),
            ):
                await messages.create_message(
                    chat_id=source_chat.id,
                    telegram_message_id=message_id,
                    sender_id=11,
                    sender_name="Анна",
                    direction="inbound",
                    source_adapter="telegram",
                    source_type="message",
                    sent_at=datetime(2026, 4, 21, 12, message_id, tzinfo=timezone.utc),
                    raw_text=text,
                    normalized_text=text,
                )

            await settings_repo.set_value(key="bot.owner_chat_id", value_text="990001")
            await settings_repo.set_value(
                key="digest.target.chat_id",
                value_text=str(digest_chat.telegram_chat_id),
            )
            await settings_repo.set_value(key="digest.target.label", value_text="@ops_digest")
            await settings_repo.set_value(key="digest.target.type", value_text="channel")
            await chat_memory.upsert_chat_memory(
                chat_id=source_chat.id,
                chat_summary_short="Чат готов к ответам.",
                chat_summary_long="В чате есть контекст для digest и reply.",
                current_state="Идёт работа по клиенту.",
                dominant_topics_json=["клиент", "договор"],
                recent_conflicts_json=[],
                pending_tasks_json=["Проверить договор"],
                linked_people_json=[{"name": "Анна"}],
                last_digest_at=datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc),
            )
            await people_memory.upsert_person_memory(
                person_key="tg:11",
                display_name="Анна",
                relationship_label="контакт",
                importance_score=0.9,
                last_summary="Анна ведёт клиента.",
                known_facts_json=["Связана с клиентом"],
                sensitive_topics_json=[],
                open_loops_json=["Договор"],
                interaction_pattern="Деловой контакт",
            )
            await reply_examples.create_example(
                chat_id=source_chat.id,
                inbound_message_id=1,
                outbound_message_id=2,
                inbound_text="Соберите финальный статус по клиенту.",
                outbound_text="Собираю и пришлю после созвона.",
                inbound_normalized="Соберите финальный статус по клиенту.",
                outbound_normalized="Собираю и пришлю после созвона.",
                context_before_json=[],
                example_type="soft_reply",
                source_person_key="tg:11",
                quality_score=0.8,
            )
            task = await tasks.create_task(
                source_chat_id=source_chat.id,
                source_message_id=None,
                title="Проверить договор",
                summary="Нужно вернуться к договору завтра.",
                due_at=datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc),
                status="active",
                needs_user_confirmation=False,
                suggested_remind_at=datetime(2026, 4, 22, 8, 0, tzinfo=timezone.utc),
                confidence=0.81,
            )
            await reminders.create_reminder(
                task_id=task.id,
                remind_at=datetime.now(timezone.utc) + timedelta(hours=2),
                status="active",
                payload_json={"source_chat_title": "Операционный чат"},
            )
            await session.commit()

            card = await SetupUIService.from_session(session).build_screen("reply")
            reminders_card = await SetupUIService.from_session(session).build_screen("reminders")

            assert "Astra AFT / Reply" in card.text
            assert "Готовых чатов: 1" in card.text
            assert "Похожие ответы: да" in card.text
            assert "Готовые чаты: 1" in card.text
            assert "Astra AFT / Reminders" in reminders_card.text
            assert "Активные напоминания: 1" in reminders_card.text

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_stage2_optional_overview_screens_render_provider_fullaccess_and_ops(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-stage2-optional" / "astra.db"
        session_path = tmp_path / "setup-stage2-optional" / "fullaccess"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("FULLACCESS_ENABLED", "true")
        monkeypatch.setenv("FULLACCESS_API_ID", "123456")
        monkeypatch.setenv("FULLACCESS_API_HASH", "test_hash")
        monkeypatch.setenv("FULLACCESS_PHONE", "+70000000000")
        monkeypatch.setenv("FULLACCESS_SESSION_PATH", str(session_path))

        session_path.with_suffix(".session").parent.mkdir(parents=True, exist_ok=True)
        session_path.with_suffix(".session").touch()

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            state = OperationalStateService(SettingRepository(session))
            await state.record_backup(path="/tmp/astra-backup.sqlite3", source_path=str(database_path))
            await state.record_export(path="/tmp/astra-export.json")
            await state.record_error("worker", message="worker: reminder_delivery lag")
            await state.record_error("provider", message="provider: timeout")
            await session.commit()

        async with runtime.session_factory() as session:
            service = SetupUIService.from_session(session)
            provider_card = await service.build_screen("provider")
            fullaccess_card = await service.build_screen("fullaccess")
            ops_card = await service.build_screen("ops")

            assert "Astra AFT / Provider" in provider_card.text
            assert "Конфиг: не настроен" in provider_card.text
            assert "Reply refine: недоступен" in provider_card.text
            assert {"Статус", "Домой", "Обновить"}.issubset(
                set(_keyboard_texts(provider_card.reply_markup))
            )

            assert "Astra AFT / Full-access" in fullaccess_card.text
            assert "Read-only барьер: активен" in fullaccess_card.text
            assert "Session: есть" in fullaccess_card.text
            assert {"Статус", "Чаты", "Sync", "Домой", "Обновить"}.issubset(
                set(_keyboard_texts(fullaccess_card.reply_markup))
            )

            assert "Astra AFT / Ops" in ops_card.text
            assert "Последний backup:" in ops_card.text
            assert "Последний export:" in ops_card.text
            assert "python -m apps.ops backup" in ops_card.text
            assert {"Doctor", "Статус", "Домой", "Обновить"}.issubset(
                set(_keyboard_texts(ops_card.reply_markup))
            )

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_stage2_reply_and_memory_pickers_and_result_cards_work(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-stage2-pickers" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            settings_repo = SettingRepository(session)
            chat_memory = ChatMemoryRepository(session)
            people_memory = PersonMemoryRepository(session)
            reply_examples = ReplyExampleRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100705,
                title="Команда клиента",
                handle="client_room",
                chat_type="group",
                is_enabled=True,
            )
            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
                raw_text="Соберите, пожалуйста, короткий статус по клиенту.",
                normalized_text="Соберите, пожалуйста, короткий статус по клиенту.",
            )
            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=2,
                sender_id=7,
                sender_name="Михаил",
                direction="outbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 9, 5, tzinfo=timezone.utc),
                raw_text="Да, собираю.",
                normalized_text="Да, собираю.",
            )
            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=3,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 9, 8, tzinfo=timezone.utc),
                raw_text="Ок, жду итог к вечеру.",
                normalized_text="Ок, жду итог к вечеру.",
            )
            await settings_repo.set_value(key="bot.owner_chat_id", value_text="990005")
            await chat_memory.upsert_chat_memory(
                chat_id=source_chat.id,
                chat_summary_short="Чат с клиентским статусом.",
                chat_summary_long="Здесь регулярно согласуют клиентский статус и сроки.",
                current_state="Нужно быстро вернуть статус по клиенту.",
                dominant_topics_json=[{"topic": "клиент", "mentions": 3}],
                recent_conflicts_json=[],
                pending_tasks_json=["Отправить статус"],
                linked_people_json=[{"person_key": "tg:11", "display_name": "Анна", "message_count": 2}],
                last_digest_at=datetime(2026, 4, 21, 8, 30, tzinfo=timezone.utc),
            )
            await people_memory.upsert_person_memory(
                person_key="tg:11",
                display_name="Анна",
                relationship_label="контакт",
                importance_score=0.8,
                last_summary="Ждёт короткие понятные апдейты.",
                known_facts_json=["Нужен статус к вечеру"],
                sensitive_topics_json=[],
                open_loops_json=["Клиентский статус"],
                interaction_pattern="Просит коротко и по делу.",
            )
            await reply_examples.create_example(
                chat_id=source_chat.id,
                inbound_message_id=1,
                outbound_message_id=2,
                inbound_text="Соберите, пожалуйста, короткий статус по клиенту.",
                outbound_text="Собираю и пришлю одним сообщением вечером.",
                inbound_normalized="Соберите, пожалуйста, короткий статус по клиенту.",
                outbound_normalized="Собираю и пришлю одним сообщением вечером.",
                context_before_json=[],
                example_type="soft_reply",
                source_person_key="tg:11",
                quality_score=0.9,
            )
            await session.commit()

            service = SetupUIService.from_session(session)
            reply_picker = await service.build_screen("reply_pick")
            memory_picker = await service.build_screen("memory_pick")

            assert "Astra AFT / Reply / Выбор чата" in reply_picker.text
            assert "Команда клиента" in reply_picker.text
            assert "client_room" in reply_picker.text
            assert "Команда клиента" in _keyboard_texts(reply_picker.reply_markup)

            assert "Astra AFT / Memory / Выбор чата" in memory_picker.text
            assert "Чат с клиентским статусом." in memory_picker.text
            assert "Команда клиента" in _keyboard_texts(memory_picker.reply_markup)

        setup_module = importlib.import_module("bot.handlers.setup")

        reply_message = FakeEditableMessage(bot=FakeBot(), chat_id=701006)
        await setup_module.handle_setup_callback(
            FakeCallback(data="ux:reply:chat:client_room", message=reply_message, bot=reply_message.bot),
            runtime.session_factory,
        )
        assert any("Astra AFT / Reply / Команда клиента" in answer.text for answer in reply_message.answers)
        assert any("Итоговая серия" in answer.text for answer in reply_message.answers)
        assert any("[OK] Риск:" in answer.text for answer in reply_message.answers)
        assert {"Похожие", "Style", "Назад", "Домой"}.issubset(
            set(_keyboard_texts(reply_message.answers[0].reply_markup))
        )

        examples_message = FakeEditableMessage(bot=FakeBot(), chat_id=701007)
        await setup_module.handle_setup_callback(
            FakeCallback(data="ux:reply:examples:client_room", message=examples_message, bot=examples_message.bot),
            runtime.session_factory,
        )
        assert any("Astra AFT / Reply / Похожие ответы" in answer.text for answer in examples_message.answers)
        assert any("Похожие прошлые ответы" in answer.text for answer in examples_message.answers)

        style_message = FakeEditableMessage(bot=FakeBot(), chat_id=701008)
        await setup_module.handle_setup_callback(
            FakeCallback(data="ux:style:status:client_room", message=style_message, bot=style_message.bot),
            runtime.session_factory,
        )
        assert any("Astra AFT / Reply / Style" in answer.text for answer in style_message.answers)
        assert any("Эффективный профиль" in answer.text for answer in style_message.answers)

        memory_message = FakeEditableMessage(bot=FakeBot(), chat_id=701009)
        await setup_module.handle_setup_callback(
            FakeCallback(data="ux:memory:chat:client_room", message=memory_message, bot=memory_message.bot),
            runtime.session_factory,
        )
        assert any("Astra AFT / Memory / Карточка" in answer.text for answer in memory_message.answers)
        assert any("Память по чату: Команда клиента" in answer.text for answer in memory_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_stage2_sources_toggle_callback_updates_screen_and_state(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-stage2-sources-toggle" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat = await chats.upsert_chat(
                telegram_chat_id=-100706,
                title="Новостной канал",
                handle="news_room",
                chat_type="channel",
                is_enabled=True,
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_id=21,
                sender_name="Редактор",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 11, 0, tzinfo=timezone.utc),
                raw_text="Сегодня обновили регламент.",
                normalized_text="Сегодня обновили регламент.",
            )
            await session.commit()

        setup_module = importlib.import_module("bot.handlers.setup")
        message = FakeEditableMessage(bot=FakeBot(), chat_id=701010)
        callback = FakeCallback(data="ux:sources:toggle:news_room", message=message, bot=message.bot)
        await setup_module.handle_setup_callback(callback, runtime.session_factory)

        assert any("Astra AFT / Sources / Обновление" in answer.text for answer in message.answers)
        assert any("Источник выключен." in answer.text for answer in message.answers)
        assert len(message.edits) == 1
        assert "Astra AFT / Sources" in message.edits[0].text

        async with runtime.session_factory() as session:
            chat = await ChatRepository(session).find_chat_by_handle_or_telegram_id("@news_room")
            assert chat is not None
            assert chat.is_enabled is False

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_stage2_digest_and_reminders_inline_actions_return_polished_cards(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-stage2-result-cards" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            settings_repo = SettingRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100707,
                title="Операционный поток",
                handle="ops_flow",
                chat_type="group",
                is_enabled=True,
            )
            digest_chat = await chats.upsert_chat(
                telegram_chat_id=-100708,
                title="Digest приёмник",
                handle="digest_sink",
                chat_type="channel",
                is_enabled=True,
            )
            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=1,
                sender_id=31,
                sender_name="Олег",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
                raw_text="Клиент подтвердил дедлайн, нужен короткий апдейт по задачам.",
                normalized_text="Клиент подтвердил дедлайн, нужен короткий апдейт по задачам.",
            )
            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=2,
                sender_id=31,
                sender_name="Олег",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                raw_text="Напомни завтра утром вернуться к договору.",
                normalized_text="Напомни завтра утром вернуться к договору.",
            )
            await settings_repo.set_value(key="bot.owner_chat_id", value_text="990007")
            await settings_repo.set_value(key="digest.target.chat_id", value_text=str(digest_chat.telegram_chat_id))
            await settings_repo.set_value(key="digest.target.label", value_text="@digest_sink")
            await settings_repo.set_value(key="digest.target.type", value_text="channel")
            await session.commit()

        setup_module = importlib.import_module("bot.handlers.setup")

        digest_message = FakeEditableMessage(bot=FakeBot(), chat_id=701011)
        await setup_module.handle_setup_callback(
            FakeCallback(data="ux:digest:run:12h", message=digest_message, bot=digest_message.bot),
            runtime.session_factory,
        )
        assert any("Astra AFT / Digest / Результат" in answer.text for answer in digest_message.answers)
        assert any("Окно:" in answer.text for answer in digest_message.answers)
        assert any("Получатель:" in answer.text for answer in digest_message.answers)
        assert any("Ключевые параметры" in answer.text for answer in digest_message.answers)
        assert {"Собрать 12h", "Собрать 24h", "Назад", "Домой", "Обновить"}.issubset(
            set(_keyboard_texts(digest_message.answers[0].reply_markup))
        )
        assert digest_message.bot.sent_messages

        reminders_message = FakeEditableMessage(bot=FakeBot(), chat_id=701012)
        await setup_module.handle_setup_callback(
            FakeCallback(data="ux:reminders:scan:24h", message=reminders_message, bot=reminders_message.bot),
            runtime.session_factory,
        )
        assert any("Astra AFT / Reminders / Скан" in answer.text for answer in reminders_message.answers)
        assert any("Новых карточек" in answer.text for answer in reminders_message.answers)
        assert any("Owner chat:" in answer.text for answer in reminders_message.answers)
        assert {"Скан 12h", "Скан 24h", "Напоминания", "Назад", "Домой", "Обновить"}.issubset(
            set(_keyboard_texts(reminders_message.answers[0].reply_markup))
        )

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_stage2_callback_navigation_renders_new_screens(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "setup-stage2-navigation" / "astra.db"
        session_path = tmp_path / "setup-stage2-navigation" / "fullaccess"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
        monkeypatch.setenv("FULLACCESS_ENABLED", "true")
        monkeypatch.setenv("FULLACCESS_API_ID", "123456")
        monkeypatch.setenv("FULLACCESS_API_HASH", "test_hash")
        monkeypatch.setenv("FULLACCESS_PHONE", "+70000000000")
        monkeypatch.setenv("FULLACCESS_SESSION_PATH", str(session_path))
        session_path.with_suffix(".session").parent.mkdir(parents=True, exist_ok=True)
        session_path.with_suffix(".session").touch()

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        setup_module = importlib.import_module("bot.handlers.setup")
        expectations = {
            "ux:provider": "Astra AFT / Provider",
            "ux:fullaccess": "Astra AFT / Full-access",
            "ux:ops": "Astra AFT / Ops",
            "ux:reply:pick": "Astra AFT / Reply / Выбор чата",
            "ux:memory:pick": "Astra AFT / Memory / Выбор чата",
            "ux:fullaccess:chats": "Astra AFT / Full-access / Чаты",
        }
        for callback_data, expected_title in expectations.items():
            message = FakeEditableMessage(bot=FakeBot(), chat_id=701013)
            callback = FakeCallback(data=callback_data, message=message, bot=message.bot)
            await setup_module.handle_setup_callback(callback, runtime.session_factory)
            assert len(message.edits) == 1
            assert expected_title in message.edits[0].text
            assert callback.answers == [(None, False)]

        await runtime.dispose()

    asyncio.run(run_assertions())


def _keyboard_texts(reply_markup) -> list[str]:
    return [button.text for row in reply_markup.inline_keyboard for button in row]
