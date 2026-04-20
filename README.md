# Astra AFT

Astra AFT — локальный MVP Telegram-ассистента. Репозиторий уже содержит базовый skeleton проекта:

- `apps/bot` для entrypoint Telegram-бота,
- `apps/worker` для фонового bootstrap/run-once сценария,
- общие границы `config`, `storage`, `services` и `adapters`,
- без реализованной бизнес-логики digest/memory/reply/reminder.

## Стек

- Python 3.12+
- aiogram
- SQLAlchemy 2.x
- Alembic
- SQLite
- pydantic-settings
- pytest

## Локальный запуск

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Перед запуском бота заполните `TELEGRAM_BOT_TOKEN` в `.env`.

## Основные команды

Запуск тестов:

```bash
pytest
```

Одноразовый bootstrap worker-процесса:

```bash
python -m apps.worker
```

Запуск Telegram-бота:

```bash
python -m apps.bot
```

Применение и создание миграций:

```bash
alembic upgrade head
alembic revision -m "описание изменения"
```

## База данных и storage

- SQLite остаётся единственной локальной БД для MVP.
- Прикладные таблицы создаются только через Alembic-миграции.
- `bootstrap_database()` на старте bot/worker доводит схему до `head`.
- ORM-модели лежат в `models/`.
- Первый слой доступа к данным лежит в `storage/repositories.py`.
- Полнотекстовый поиск по сообщениям подготовлен через SQLite FTS5: виртуальная таблица `messages_fts` и триггеры на `messages`.

## Текущее покрытие

Сейчас уже есть:

- структура пакетов и entrypoint’ов,
- настройки из окружения,
- async runtime для SQLite и bootstrap через Alembic,
- начальная ORM-схема для `chats/messages/digests/digest_items/people_memory/chat_memory/tasks/reminders/settings`,
- репозиторный слой для `chats`, `messages`, `digests` и `settings`,
- тонкая обвязка bot/worker,
- первая реальная миграция локальной схемы хранения.

Пока намеренно не реализованы:

- генерация digest,
- суммаризация memory,
- reply suggestion,
- извлечение reminder/task из сообщений,
- полноценная синхронизация источников Telegram,
- бизнес-логика для `business/` и `fullaccess/`.
