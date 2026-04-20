from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from config.settings import Settings
from storage.base import Base


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
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return DatabaseRuntime(
        engine=engine,
        session_factory=session_factory,
        database_url=settings.database_url,
    )


async def bootstrap_database(runtime: DatabaseRuntime) -> None:
    async with runtime.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
