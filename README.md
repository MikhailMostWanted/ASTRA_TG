# Astra AFT

Astra AFT is a local-first Telegram assistant MVP. This repository currently contains only the foundational project skeleton:

- `apps/bot` for the Telegram bot entrypoint,
- `apps/worker` for background/bootstrap tasks,
- shared configuration, storage, and adapter boundaries,
- no real digest/memory/reply/reminder logic yet.

## Stack

- Python 3.12+
- aiogram
- SQLAlchemy 2.x
- Alembic
- SQLite
- pydantic-settings
- pytest

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill `TELEGRAM_BOT_TOKEN` in `.env` before starting the bot.

## Local commands

Run tests:

```bash
pytest
```

Run the one-shot worker bootstrap:

```bash
python -m apps.worker
```

Run the Telegram bot:

```bash
python -m apps.bot
```

Initialize or inspect migrations:

```bash
alembic upgrade head
alembic revision -m "describe change"
```

## Current scope

Implemented now:

- project/package structure,
- environment-based settings,
- async SQLite bootstrap,
- thin bot handler wiring,
- stub adapters for future provider layers,
- Alembic baseline configuration.

Still intentionally stubbed:

- digest engine,
- memory layer,
- reply suggestion engine,
- reminder extraction,
- Telegram source syncing beyond the bot shell,
- business/full-access adapter behavior.
