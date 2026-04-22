import asyncio
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from services.providers.manager import ProviderManager
from services.startup import BotStartupService
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


def _build_status_service(session, *, settings: Settings | None = None) -> BotStatusService:
    effective_settings = settings or Settings()
    message_repository = MessageRepository(session)
    setting_repository = SettingRepository(session)
    return BotStatusService(
        chat_repository=ChatRepository(session),
        setting_repository=setting_repository,
        system_repository=SystemRepository(session),
        message_repository=message_repository,
        digest_repository=DigestRepository(session),
        chat_memory_repository=ChatMemoryRepository(session),
        person_memory_repository=PersonMemoryRepository(session),
        style_profile_repository=StyleProfileRepository(session),
        chat_style_override_repository=ChatStyleOverrideRepository(session),
        task_repository=TaskRepository(session),
        reminder_repository=ReminderRepository(session),
        reply_example_repository=ReplyExampleRepository(session),
        provider_manager=ProviderManager.from_settings(effective_settings),
        fullaccess_auth_service=FullAccessAuthService(
            settings=effective_settings,
            setting_repository=setting_repository,
            message_repository=message_repository,
        ),
    )


def test_onboarding_message_shows_first_run_flow() -> None:
    message = BotStartupService().build_onboarding_message()

    assert "Astra AFT" in message
    assert "/setup" in message
    assert "источник" in message.lower()
    assert "дайджест" in message.lower()
    assert "память" in message.lower()
    assert "ответ" in message.lower()
    assert "напомин" in message.lower()
    assert "full-access" in message.lower()
    assert "/source_add" in message
    assert "/memory_rebuild" in message
    assert "/checklist" in message
    assert "/doctor" in message


def test_help_message_groups_commands_by_section() -> None:
    message = BotStartupService().build_help_message()

    assert "Настройка" in message
    assert "Источники" in message
    assert "Digest" in message
    assert "Память" in message
    assert "Ответы" in message
    assert "Напоминания" in message
    assert "Провайдер" in message
    assert "Full-access experimental" in message
    assert "Диагностика" in message
    assert "/setup" in message
    assert "/onboarding" in message
    assert "/checklist" in message
    assert "/doctor" in message
    assert "/status" in message


def test_operational_messages_for_empty_database(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "operational-empty" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            service = _build_status_service(session)

            status_text = await service.build_status_message()
            checklist_text = await service.build_checklist_message()
            doctor_text = await service.build_doctor_message()

            assert "✅ Короткий статус" in status_text
            assert "Следующий шаг" in status_text
            assert "/setup" in status_text
            assert "/checklist" in status_text
            assert "[WARN] Личный чат" in checklist_text
            assert "[WARN] Источник" in checklist_text
            assert "[WARN] Сообщения" in checklist_text
            assert "[OPT] Провайдер" in checklist_text
            assert "Что уже ок" in doctor_text
            assert "На что смотреть" in doctor_text
            assert "Что исправить дальше" in doctor_text
            assert "владелец" in doctor_text.lower() or "owner chat" in doctor_text.lower()
            assert "нет активных источников" in doctor_text.lower()
            assert "в бд ещё нет сообщений" in doctor_text.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_checklist_distinguishes_sources_messages_and_memory(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "operational-partial" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            settings_repo = SettingRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100700,
                title="Команда запуска",
                handle="launch_team",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            service = _build_status_service(session)
            checklist_without_messages = await service.build_checklist_message()
            assert "[OK] Источник" in checklist_without_messages
            assert "[WARN] Сообщения" in checklist_without_messages

            await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=1,
                sender_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
                raw_text="Соберите статус по запуску.",
                normalized_text="Соберите статус по запуску.",
            )
            await settings_repo.set_value(key="bot.owner_chat_id", value_text="777001")
            await session.commit()

            checklist_with_messages = await service.build_checklist_message()
            doctor_text = await service.build_doctor_message()

            assert "[OK] Сообщения" in checklist_with_messages
            assert "[WARN] Память" in checklist_with_messages
            assert "[WARN] Ответы" in checklist_with_messages
            assert "memory cards" in doctor_text.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_checklist_accepts_fully_ready_system(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "operational-ready" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            settings_repo = SettingRepository(session)
            chat_memory_repo = ChatMemoryRepository(session)
            people_memory_repo = PersonMemoryRepository(session)
            tasks = TaskRepository(session)
            reminders = ReminderRepository(session)
            reply_examples = ReplyExampleRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100800,
                title="Операционный чат",
                handle="ops_team",
                chat_type="group",
                is_enabled=True,
            )
            digest_chat = await chats.upsert_chat(
                telegram_chat_id=-100801,
                title="Digest",
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
            await settings_repo.set_value(key="digest.target.chat_id", value_text=str(digest_chat.telegram_chat_id))
            await settings_repo.set_value(key="digest.target.label", value_text="@ops_digest")
            await settings_repo.set_value(key="digest.target.type", value_text="channel")
            await chat_memory_repo.upsert_chat_memory(
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
            await people_memory_repo.upsert_person_memory(
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
            task = await tasks.create_task(
                source_chat_id=source_chat.id,
                source_message_id=None,
                title="Проверить договор",
                summary="Нужно вернуться к договору завтра.",
                due_at=None,
                suggested_remind_at=datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc),
                status="active",
                confidence=0.9,
                needs_user_confirmation=False,
            )
            await reminders.create_reminder(
                task_id=task.id,
                remind_at=datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc),
                status="active",
                payload_json={"chat_title": source_chat.title},
            )
            await reply_examples.create_example(
                chat_id=source_chat.id,
                inbound_message_id=None,
                outbound_message_id=None,
                inbound_text="Соберите финальный статус по клиенту.",
                outbound_text="Собираю, вернусь с апдейтом после созвона.",
                inbound_normalized="соберите финальный статус по клиенту",
                outbound_normalized="собираю вернусь с апдейтом после созвона",
                context_before_json=[],
                example_type="request",
                source_person_key="tg:11",
                quality_score=0.88,
            )
            await session.commit()

            service = _build_status_service(session)
            checklist_text = await service.build_checklist_message()
            doctor_text = await service.build_doctor_message()
            status_text = await service.build_status_message()

            assert "[OK] Личный чат" in checklist_text
            assert "[OK] Получатель дайджеста" in checklist_text
            assert "[OK] Память" in checklist_text
            assert "[OK] Ответы" in checklist_text
            assert "[OK] Напоминания" in checklist_text
            assert "[OPT] Провайдер" in checklist_text
            assert "Критичных проблем не найдено" in doctor_text
            assert "✅ Основной путь готов: 9/9." in status_text

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_status_and_doctor_include_operational_hardening_context(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "operational-hardening" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("LLM_ENABLED", "false")
        monkeypatch.setenv("FULLACCESS_ENABLED", "false")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            settings_repo = SettingRepository(session)
            await settings_repo.set_value(
                key="ops.error.provider.last",
                value_json={
                    "timestamp": "2026-04-21T12:00:00+00:00",
                    "message": "provider timeout",
                },
            )
            await settings_repo.set_value(
                key="ops.error.worker.last",
                value_json={
                    "timestamp": "2026-04-21T12:05:00+00:00",
                    "message": "reminder failed",
                },
            )
            await settings_repo.set_value(
                key="ops.startup.bot.last",
                value_json={
                    "warnings": ["owner chat неизвестен"],
                    "critical_issues": [],
                },
            )
            await session.commit()

            service = _build_status_service(session)
            status_text = await service.build_status_message()
            doctor_text = await service.build_doctor_message()

            assert "бэкап" in status_text.lower()
            assert "экспорт" in status_text.lower()
            assert "startup" in doctor_text.lower()
            assert "provider timeout" in doctor_text.lower()
            assert "reminder failed" in doctor_text.lower()

        await runtime.dispose()

    asyncio.run(run_assertions())
