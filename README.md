# Astra AFT

Astra AFT — локальный MVP Telegram-ассистента. Репозиторий уже содержит базовый skeleton проекта:

- `apps/bot` для entrypoint Telegram-бота,
- `apps/worker` для фонового bootstrap/run-once сценария,
- общие границы `config`, `storage`, `services` и `adapters`,
- ingest MVP для накопления входящих сообщений из разрешённых Telegram-источников,
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

Команды Telegram-бота:

- `/start` — короткий онбординг и порядок первого запуска.
- `/help` — список доступных команд.
- `/status` — техническая сводка по состоянию проекта и ingest-метрикам.
- `/sources` — все зарегистрированные источники из allowlist со статистикой сообщений.
- `/source_add <chat_id|@username>` — добавить источник в allowlist.
- `/source_disable <chat_id|@username>` — выключить источник.
- `/source_enable <chat_id|@username>` — включить источник обратно.
- `/digest_target <chat_id|@username>` — сохранить чат или канал доставки digest.
- `/settings` — показать базовые настройки Astra AFT.

Для `/source_add` и `/digest_target` поддержан best-effort сценарий через форвард или reply:

- можно переслать сообщение из канала/группы и вызвать команду без аргументов;
- если Telegram не отдаёт все поля источника, бот честно сообщает об ограничении и сохраняет минимум возможных данных.

## Ingest MVP

Бот теперь сохраняет входящие сообщения в `messages`, но только для источников, которые:

- присутствуют в allowlist (`chats`);
- включены (`is_enabled = true`);
- не исключены из digest-контура (`exclude_from_digest = false`);
- не являются сервисной личкой с ботом.

Что попадает в ingest:

- обычные текстовые сообщения;
- подписи к медиа, если текста нет;
- media-only сообщения из разрешённых источников;
- сообщения и посты из групп, супергрупп и каналов, если бот реально получает update.

Что не попадает в ingest:

- сообщения из неразрешённых источников;
- сообщения из выключенных источников;
- сообщения из источников, исключённых из digest;
- сервисные команды в личке с ботом.

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
- Сервисный ingest находится в `services/message_ingest.py`, а нормализация входящих сообщений — в `services/message_normalizer.py`.

## Текущее покрытие

Сейчас уже есть:

- структура пакетов и entrypoint’ов,
- настройки из окружения,
- async runtime для SQLite и bootstrap через Alembic,
- начальная ORM-схема для `chats/messages/digests/digest_items/people_memory/chat_memory/tasks/reminders/settings`,
- репозиторный слой для `chats`, `messages`, `digests` и `settings`,
- ingest сообщений только из разрешённых Telegram-источников,
- тонкая обвязка bot/worker,
- первая реальная миграция локальной схемы хранения.

Пока намеренно не реализованы:

- генерация digest,
- суммаризация memory,
- reply suggestion,
- извлечение reminder/task из сообщений,
- полноценная синхронизация источников Telegram,
- бизнес-логика для `business/` и `fullaccess/`.

## Как проверить ingest вручную

1. Примени миграции и запусти бота:

```bash
alembic upgrade head
python -m apps.bot
```

2. Добавь канал или группу в allowlist через `/source_add <chat_id|@username>` или форвард + `/source_add`.

3. Убедись, что бот добавлен в этот источник и источник не выключен.

4. Отправь в разрешённый источник текстовое сообщение или медиа с подписью.

5. Проверь результат:

- `/status` покажет `Ingest: активен`, число сохранённых сообщений и время последнего сохранения;
- `/sources` покажет счётчики сообщений по источникам;
- в SQLite появятся записи в `messages`.

Пример быстрой проверки базы:

```bash
sqlite3 var/astra.db "SELECT telegram_message_id, chat_id, raw_text, normalized_text, has_media, media_type, sent_at FROM messages ORDER BY id DESC LIMIT 10;"
```
