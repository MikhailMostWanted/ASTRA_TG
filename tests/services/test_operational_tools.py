import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings
from services.operational_tools import OperationalBackupService, OperationalExportService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, MessageRepository, SettingRepository


def test_operational_backup_and_export_create_artifacts(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "ops-tools" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("LLM_ENABLED", "false")
        monkeypatch.setenv("FULLACCESS_ENABLED", "false")

        settings = Settings()
        runtime = build_database_runtime(settings)
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            chat = await chats.upsert_chat(
                telegram_chat_id=-100701,
                title="Ops",
                handle="ops",
                chat_type="group",
                is_enabled=True,
            )
            await messages.create_message(
                chat_id=chat.id,
                telegram_message_id=1,
                sender_name="Анна",
                direction="inbound",
                source_adapter="telegram",
                source_type="message",
                sent_at=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
                raw_text="Проверить operational export",
                normalized_text="Проверить operational export",
            )
            await SettingRepository(session).set_value(key="bot.owner_chat_id", value_text="777001")
            await session.commit()

        backup_result = await OperationalBackupService(settings).create_backup()
        export_result = await OperationalExportService(
            settings=settings,
            session_factory=runtime.session_factory,
        ).export_summary()

        assert backup_result.created is True
        assert backup_result.path.exists()
        assert backup_result.path.parent.name == "backups"

        assert export_result.path.exists()
        payload = json.loads(export_result.path.read_text(encoding="utf-8"))
        assert payload["counts"]["sources"] == 1
        assert payload["counts"]["messages"] == 1
        assert payload["provider"]["enabled"] is False
        assert payload["fullaccess"]["enabled"] is False
        assert "owner_chat_id" in payload["operational"]

        await runtime.dispose()

    asyncio.run(run_assertions())
