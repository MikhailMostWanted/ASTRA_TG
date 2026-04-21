import asyncio
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter
from services.reminder_service import ReminderService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    MessageRepository,
    ReminderRepository,
    SettingRepository,
    TaskRepository,
)


def test_reminder_scan_and_candidate_decisions(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reminder-pipeline" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)

            active_chat = await chats.upsert_chat(
                telegram_chat_id=-100500,
                title="Команда продукта",
                handle="product_team",
                chat_type="group",
                is_enabled=True,
            )
            excluded_chat = await chats.upsert_chat(
                telegram_chat_id=-100501,
                title="Скрытый чат",
                chat_type="group",
                is_enabled=True,
                exclude_from_memory=True,
            )
            await session.commit()

            await messages.create_message(
                chat_id=active_chat.id,
                telegram_message_id=11,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
                raw_text="Не забудь завтра в 09:30 отправить финальный договор клиенту",
                normalized_text="не забудь завтра в 09:30 отправить финальный договор клиенту",
            )
            await messages.create_message(
                chat_id=active_chat.id,
                telegram_message_id=12,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 5, tzinfo=timezone.utc),
                raw_text="Ок, понял, спасибо",
                normalized_text="ок, понял, спасибо",
            )
            await messages.create_message(
                chat_id=excluded_chat.id,
                telegram_message_id=13,
                sender_name="Игорь",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 15, tzinfo=timezone.utc),
                raw_text="Напомни через час про счёт",
                normalized_text="напомни через час про счёт",
            )
            await session.commit()

            service = ReminderService(
                chat_repository=chats,
                message_repository=messages,
                chat_memory_repository=ChatMemoryRepository(session),
                setting_repository=SettingRepository(session),
                task_repository=TaskRepository(session),
                reminder_repository=ReminderRepository(session),
                extractor=ReminderExtractor(),
                formatter=ReminderFormatter(),
            )

            scan_result = await service.scan(
                window_argument="24h",
                source_reference=None,
                now=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
            )

            assert scan_result.created_count == 1
            assert scan_result.skipped_existing_count == 0
            assert len(scan_result.cards) == 1
            assert "Найдено кандидатов: 1" in scan_result.summary_text
            assert "финальный договор" in scan_result.cards[0].text.lower()
            assert "Команда продукта" in scan_result.cards[0].text
            assert scan_result.cards[0].reply_markup is not None

            candidates = await TaskRepository(session).list_candidates()
            assert len(candidates) == 1
            assert candidates[0].status == "candidate"
            assert candidates[0].needs_user_confirmation is True

            approve_result = await service.approve_candidate(
                task_id=candidates[0].id,
                now=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
            )
            await session.commit()

            assert approve_result.task.status == "active"
            assert approve_result.reminder.status == "active"
            assert approve_result.task.needs_user_confirmation is False

            tasks_text = await service.build_tasks_message()
            reminders_text = await service.build_reminders_message()

            assert "Astra AFT / Reminders / Tasks" in tasks_text
            assert "финальный договор" in tasks_text.lower()
            assert "Команда продукта" in tasks_text
            assert "Astra AFT / Reminders" in reminders_text
            assert "подтверждено: да" in reminders_text.lower()

            await messages.create_message(
                chat_id=active_chat.id,
                telegram_message_id=14,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 10, tzinfo=timezone.utc),
                raw_text="Напомни вечером проверить оплату",
                normalized_text="напомни вечером проверить оплату",
            )
            await messages.create_message(
                chat_id=active_chat.id,
                telegram_message_id=15,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 10, 12, tzinfo=timezone.utc),
                raw_text="Созвонимся завтра утром по релизу",
                normalized_text="созвонимся завтра утром по релизу",
            )
            await session.commit()

            second_scan = await service.scan(
                window_argument="24h",
                source_reference="@product_team",
                now=datetime(2026, 4, 20, 10, 15, tzinfo=timezone.utc),
            )
            assert second_scan.created_count == 2

            updated_candidates = await TaskRepository(session).list_candidates()
            assert len(updated_candidates) == 2

            reject_result = await service.reject_candidate(updated_candidates[0].id)
            postpone_result = await service.postpone_candidate(
                task_id=updated_candidates[1].id,
                now=datetime(2026, 4, 20, 10, 15, tzinfo=timezone.utc),
            )
            await session.commit()

            assert reject_result.task.status == "dismissed"
            assert reject_result.reminder.status == "dismissed"
            assert postpone_result.task.status == "active"
            assert postpone_result.reminder.status == "active"
            assert postpone_result.original_remind_at is not None
            assert postpone_result.reminder.remind_at > postpone_result.original_remind_at

        await runtime.dispose()

    asyncio.run(run_assertions())
