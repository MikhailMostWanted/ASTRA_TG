import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from services.reminder_delivery import ReminderDeliveryService
from services.reminder_formatter import ReminderFormatter
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatRepository,
    MessageRepository,
    ReminderRepository,
    SettingRepository,
    TaskRepository,
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
        sent = FakeSentMessage(
            chat_id=chat_id,
            text=text,
            message_id=len(self.sent_messages) + 1,
        )
        self.sent_messages.append(sent)
        return type("FakeTelegramMessage", (), {"message_id": sent.message_id})()


def test_worker_delivers_due_reminder_once(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "reminder-worker" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            settings_repo = SettingRepository(session)
            tasks = TaskRepository(session)
            reminders = ReminderRepository(session)

            source_chat = await chats.upsert_chat(
                telegram_chat_id=-100700,
                title="Команда запуска",
                chat_type="group",
                is_enabled=True,
            )
            await session.commit()

            source_message = await messages.create_message(
                chat_id=source_chat.id,
                telegram_message_id=21,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
                raw_text="Не забудь сегодня в 11:00 проверить выкладку",
                normalized_text="не забудь сегодня в 11:00 проверить выкладку",
            )
            task = await tasks.create_task(
                source_chat_id=source_chat.id,
                source_message_id=source_message.id,
                title="Проверить выкладку",
                summary="Сообщение от Анны: не забудь сегодня в 11:00 проверить выкладку",
                due_at=datetime(2026, 4, 20, 11, 0, tzinfo=timezone.utc),
                suggested_remind_at=datetime(2026, 4, 20, 10, 45, tzinfo=timezone.utc),
                status="active",
                confidence=0.92,
                needs_user_confirmation=False,
            )
            await reminders.create_reminder(
                task_id=task.id,
                remind_at=datetime(2026, 4, 20, 10, 45, tzinfo=timezone.utc),
                status="active",
                payload_json={
                    "source_message_preview": "Не забудь сегодня в 11:00 проверить выкладку",
                    "reason": ["триггер: не забудь", "время: 11:00"],
                },
            )
            await settings_repo.set_value(key="bot.owner_chat_id", value_text="555001")
            await session.commit()

            fake_bot = FakeBot()
            service = ReminderDeliveryService(
                setting_repository=settings_repo,
                reminder_repository=reminders,
                formatter=ReminderFormatter(),
            )

            first_run = await service.deliver_due_reminders(
                sender=fake_bot,
                now=datetime(2026, 4, 20, 10, 50, tzinfo=timezone.utc),
            )
            await session.commit()

            assert first_run.sent_count == 1
            assert len(fake_bot.sent_messages) == 1
            assert fake_bot.sent_messages[0].chat_id == 555001
            assert "Проверить выкладку" in fake_bot.sent_messages[0].text
            assert "Команда запуска" in fake_bot.sent_messages[0].text

            delivered = await reminders.list_all()
            assert delivered[0].status == "delivered"
            assert delivered[0].last_notification_at == datetime(
                2026, 4, 20, 10, 50, tzinfo=timezone.utc
            )

            second_run = await service.deliver_due_reminders(
                sender=fake_bot,
                now=datetime(2026, 4, 20, 11, 0, tzinfo=timezone.utc),
            )
            await session.commit()

            assert second_run.sent_count == 0
            assert len(fake_bot.sent_messages) == 1

        await runtime.dispose()

    asyncio.run(run_assertions())
