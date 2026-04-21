import asyncio
from pathlib import Path

from sqlalchemy import inspect, text

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime


EXPECTED_TABLES = {
    "chat_memory",
    "chat_style_overrides",
    "chats",
    "digest_items",
    "digests",
    "messages",
    "messages_fts",
    "people_memory",
    "reply_examples",
    "reply_examples_fts",
    "reminders",
    "settings",
    "style_profiles",
    "tasks",
}


def test_database_bootstrap_applies_migrations_and_creates_schema(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "bootstrap" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        settings = Settings()
        runtime = build_database_runtime(settings)

        await bootstrap_database(runtime)

        assert database_path.parent.exists()
        assert database_path.exists()

        async with runtime.engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            index_rows = await connection.execute(text("PRAGMA index_list('messages')"))
            fts_rows = await connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = 'messages' "
                    "ORDER BY name"
                )
            )
            reply_examples_fts_rows = await connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = 'reply_examples' "
                    "ORDER BY name"
                )
            )
            revision_row = await connection.execute(text("SELECT version_num FROM alembic_version"))

        assert EXPECTED_TABLES.issubset(table_names)
        assert "ix_messages_chat_id_sent_at" in {row[1] for row in index_rows}
        assert {row[0] for row in fts_rows} == {
            "messages_ai",
            "messages_au",
            "messages_bu",
        }
        assert {row[0] for row in reply_examples_fts_rows} == {
            "reply_examples_ai",
            "reply_examples_au",
            "reply_examples_bu",
        }
        assert revision_row.scalar_one() is not None

        await runtime.dispose()

    asyncio.run(run_assertions())
