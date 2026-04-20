from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from config.settings import Settings
from services.persona_rules import (
    DEFAULT_OWNER_PERSONA_CORE,
    DEFAULT_PERSONA_ENABLED,
    DEFAULT_PERSONA_GUARDRAILS,
    DEFAULT_PERSONA_VERSION,
)
from storage.migrations import upgrade_database_async
from storage.repositories import SettingRepository


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
    await _seed_default_settings(runtime.session_factory)


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


async def _seed_default_settings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = SettingRepository(session)
        changed = False
        changed |= await _ensure_json_setting(
            repository,
            key="persona.core",
            value=DEFAULT_OWNER_PERSONA_CORE,
        )
        changed |= await _ensure_json_setting(
            repository,
            key="persona.guardrails",
            value=DEFAULT_PERSONA_GUARDRAILS,
        )
        changed |= await _ensure_json_setting(
            repository,
            key="persona.enabled",
            value=DEFAULT_PERSONA_ENABLED,
        )
        changed |= await _ensure_text_setting(
            repository,
            key="persona.version",
            value=DEFAULT_PERSONA_VERSION,
        )
        if changed:
            await session.commit()


async def _ensure_json_setting(
    repository: SettingRepository,
    *,
    key: str,
    value: dict[str, object],
) -> bool:
    if await repository.get_by_key(key) is not None:
        return False
    await repository.set_value(key=key, value_json=value)
    return True


async def _ensure_text_setting(
    repository: SettingRepository,
    *,
    key: str,
    value: str,
) -> bool:
    if await repository.get_by_key(key) is not None:
        return False
    await repository.set_value(key=key, value_text=value)
    return True
