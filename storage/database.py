from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from config.settings import Settings
from storage.migrations import upgrade_database_async


@dataclass(slots=True)
class DatabaseRuntime:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    database_url: str

    async def dispose(self) -> None:
        await self.engine.dispose()


def build_database_runtime(settings: Settings) -> DatabaseRuntime:
    sqlite_database_path = settings.sqlite_database_path
    if sqlite_database_path is not None:
        sqlite_database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(settings.database_url, future=True)
    _configure_sqlite_engine(engine=engine, sqlite_database_path=sqlite_database_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return DatabaseRuntime(
        engine=engine,
        session_factory=session_factory,
        database_url=settings.database_url,
    )


async def bootstrap_database(runtime: DatabaseRuntime) -> None:
    await upgrade_database_async(runtime.database_url)


def _configure_sqlite_engine(
    *,
    engine: AsyncEngine,
    sqlite_database_path: Path | None,
) -> None:
    if sqlite_database_path is None:
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()
