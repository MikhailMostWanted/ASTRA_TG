from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = REPOSITORY_ROOT / "alembic.ini"
MIGRATIONS_PATH = REPOSITORY_ROOT / "migrations"


def build_alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.set_main_option("prepend_sys_path", str(REPOSITORY_ROOT))
    config.attributes["database_url"] = database_url
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    command.upgrade(build_alembic_config(database_url), revision)


async def upgrade_database_async(database_url: str, revision: str = "head") -> None:
    await asyncio.to_thread(upgrade_database, database_url, revision)
