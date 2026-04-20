# Astra AFT

Astra AFT — локальный MVP Telegram-ассистента. Репозиторий уже содержит базовый skeleton проекта:

- `apps/bot` для entrypoint Telegram-бота,
- `apps/worker` для фонового bootstrap/run-once сценария,
- общие границы `config`, `storage`, `services` и `adapters`,
- ingest MVP для накопления входящих сообщений из разрешённых Telegram-источников,
- первый локальный digest MVP без LLM поверх уже сохранённых сообщений.
- первый локальный memory MVP по чатам и людям поверх уже сохранённых сообщений.
- первый локальный reply coach MVP по уже сохранённым сообщениям и memory-картам.

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
- `/memory_rebuild [chat_id|@username]` — пересобрать memory по локальной БД.
- `/chat_memory <chat_id|@username>` — показать memory-card по чату.
- `/person_memory <person_key|имя|@username>` — показать memory-card по человеку.
- `/digest_target <chat_id|@username>` — сохранить чат или канал доставки digest.
- `/digest_now [12h|24h|3d]` — вручную собрать digest по сохранённым сообщениям.
- `/reply <chat_id|@username>` — получить одну локальную подсказку ответа по конкретному чату.
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

## Digest MVP

Теперь поверх `messages` подключён первый реальный digest-сценарий:

- `/digest_now` читает только локальную БД, без прямого чтения Telegram в момент вызова;
- в digest попадают только разрешённые и активные источники;
- источники с `exclude_from_digest = true` пропускаются;
- digest строится детерминированным локальным движком без LLM;
- итог сохраняется в `digests` и `digest_items`;
- бот показывает preview в текущем чате и, если задан `digest target`, одновременно публикует digest туда же.

Поддержанные окна для ручного запуска:

- `/digest_now`
- `/digest_now 12h`
- `/digest_now 24h`
- `/digest_now 3d`

## Memory MVP

Теперь поверх `messages` и `chats` подключён первый реальный memory-layer без LLM:

- `/memory_rebuild` читает только локальную SQLite-БД и не ходит в Telegram напрямую;
- по умолчанию rebuild идёт по активным `memory`-источникам;
- `/memory_rebuild <chat_id|@username>` позволяет пересобрать память только по одному источнику;
- результаты сохраняются в `chat_memory` и `people_memory`;
- `/chat_memory` показывает короткую memory-card по чату;
- `/person_memory` показывает короткую memory-card по человеку;
- все summary и карточки строятся детерминированно, локальными эвристиками, без внешних NLP/LLM.

Что попадает в chat memory:

- краткая и развёрнутая сводка по чату;
- текущее состояние обсуждения;
- доминирующие темы;
- открытые хвосты и напряжённые сигналы;
- основные участники;
- время последнего digest по источнику, если он уже был.

Что попадает в people memory:

- display name и стабильный `person_key`;
- число связанных сообщений и простая importance-эвристика;
- паттерн взаимодействия;
- подтверждённые факты из метаданных общения;
- чувствительные темы по безопасным ключевым признакам;
- открытые хвосты по вопросам/обещаниям из сообщений.

## Reply MVP

Теперь поверх `messages`, `chat_memory` и `people_memory` подключён первый локальный reply coach без внешних LLM:

- `/reply <chat_id|@username>` работает только по локальной SQLite-БД и уже сохранённым сообщениям;
- движок берёт последние 20–40 сообщений, память по чату и связанным людям, а затем выбирает один лучший draft-ответ;
- reply layer остаётся эвристическим и детерминированным: без OpenAI, Anthropic и локальных моделей;
- текущая цель слоя — не style cloning, а безопасный короткий Telegram-draft с понятной причиной выбора;
- в ответе бот показывает сам draft, краткое объяснение, риск и уверенность.

Что умеет reply engine на этом шаге:

- различать вопрос/уточнение, просьбу, лёгкий бытовой разговор, напряжённый фрагмент и ситуацию, где лучше не отвечать сразу;
- опираться на `chat_memory.current_state`, `pending_tasks`, `recent_conflicts`, `people_memory.interaction_pattern` и `open_loops`;
- честно говорить, если чата нет, данных пока мало или последнее сохранённое сообщение уже от пользователя.

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
- Memory-сервисы лежат в `services/memory_builder.py`, `services/chat_memory_builder.py`, `services/people_memory_builder.py` и `services/memory_formatter.py`.
- Reply-сервисы лежат в `services/reply_context_builder.py`, `services/reply_classifier.py`, `services/reply_strategy.py`, `services/reply_engine.py` и `services/reply_formatter.py`.

## Текущее покрытие

Сейчас уже есть:

- структура пакетов и entrypoint’ов,
- настройки из окружения,
- async runtime для SQLite и bootstrap через Alembic,
- начальная ORM-схема для `chats/messages/digests/digest_items/people_memory/chat_memory/tasks/reminders/settings`,
- репозиторный слой для `chats`, `messages`, `digests` и `settings`,
- ingest сообщений только из разрешённых Telegram-источников,
- ручной digest по уже накопленным сообщениям из локальной БД,
- локальный memory layer по чатам и людям из уже накопленных сообщений,
- локальный reply coach MVP по чатам из локальной БД и memory-карт,
- тонкая обвязка bot/worker,
- первая реальная миграция локальной схемы хранения.

Пока намеренно не реализованы:

- внешний provider layer для reply,
- style cloning личности,
- автоответ или one-tap send,
- извлечение reminder/task из сообщений,
- полноценная синхронизация источников Telegram,
- бизнес-логика для `business/` и `fullaccess/`.

## Как накопить сообщения и получить первую reply-подсказку

1. Примени миграции и запусти бота:

```bash
alembic upgrade head
python -m apps.bot
```

2. Добавь канал или группу в allowlist через `/source_add <chat_id|@username>` или форвард + `/source_add`.

3. Накопи в этом источнике хотя бы несколько сообщений, чтобы у бота появился локальный контекст.

4. Для более точной подсказки пересобери память:

- вызови `/memory_rebuild`;
- или `/memory_rebuild @mychannel` для одного источника.

5. Получи первую подсказку ответа:

- `/reply @mychannel`
- `/reply -1001234567890`

Бот покажет:

- какой чат анализировался;
- на какое последнее сообщение он ориентировался;
- один основной draft-ответ;
- краткое объяснение выбора;
- риск и уверенность.

Если данных пока мало, бот честно скажет об этом и не будет придумывать reply из воздуха.

## Как проверить ingest, memory, reply и digest вручную

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

6. Собери digest вручную:

- вызови `/digest_now`;
- при необходимости укажи окно: `/digest_now 12h` или `/digest_now 3d`;
- если задан `/digest_target`, бот покажет preview и отправит итог туда же.

7. Пересобери memory вручную:

- вызови `/memory_rebuild` для всех активных источников;
- или `/memory_rebuild @mychannel` для одного источника;
- после этого проверь `/chat_memory @mychannel` и `/person_memory Анна`.

8. Проверь reply suggestions:

- вызови `/reply @mychannel`;
- если локального контекста уже хватает, бот вернёт короткий draft, объяснение, риск и уверенность;
- если последнее сообщение уже твоё или контекста мало, бот честно сообщит об этом.

Пример быстрой проверки базы:

```bash
sqlite3 var/astra.db "SELECT telegram_message_id, chat_id, raw_text, normalized_text, has_media, media_type, sent_at FROM messages ORDER BY id DESC LIMIT 10;"
```

Проверка chat memory:

```bash
sqlite3 var/astra.db "SELECT chat_id, chat_summary_short, current_state, updated_at FROM chat_memory ORDER BY updated_at DESC LIMIT 10;"
```

Проверка people memory:

```bash
sqlite3 var/astra.db "SELECT person_key, display_name, importance_score, updated_at FROM people_memory ORDER BY importance_score DESC, updated_at DESC LIMIT 10;"
```

Проверка сохранённых digest:

```bash
sqlite3 var/astra.db "SELECT id, window_start, window_end, summary_short, delivered_to_chat_id, delivered_message_id FROM digests ORDER BY id DESC LIMIT 5;"
sqlite3 var/astra.db "SELECT digest_id, source_chat_id, title, summary FROM digest_items ORDER BY digest_id DESC, sort_order ASC LIMIT 20;"
```
