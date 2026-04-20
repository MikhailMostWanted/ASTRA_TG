# Заметка по архитектуре

## Назначение

Репозиторий остаётся локальным single-user MVP. Первая полезная ценность — digest-сводки по выбранным Telegram-источникам. Memory, reply suggestions, reminders и расширение провайдеров запланированы, но пока не реализованы как бизнес-логика.

## Зоны ответственности модулей

- `apps/` содержит только runnable entrypoint’ы.
- `bot/` содержит aiogram routing и тонкие Telegram-handlers.
- `bot/` теперь также даёт Telegram-интерфейс для управления allowlist источников, базовыми настройками digest и приёма входящих updates для ingest.
- `worker/` содержит точки входа для фонового bootstrap/run-once сценария.
- `services/` содержит прикладную логику, которую вызывают handlers и entrypoint’ы, включая реестр источников, digest target, ingest pipeline, digest engine и статусные сводки.
- `config/` содержит общие настройки из окружения.
- `storage/` содержит SQLAlchemy runtime, bootstrap через Alembic и репозитории доступа к данным.
- `models/` содержит ORM-схему SQLite для MVP-сущностей.
- `schemas/` содержит typed payloads и transport models.
- `adapters/` задаёт переиспользуемые границы адаптеров.
- `telegram_bot/`, `business/` и `fullaccess/` содержат реализации адаптеров для будущих режимов доступа.
- `migrations/` содержит конфигурацию Alembic и ревизии схемы.

## Правила границ

- Держать Telegram-handlers тонкими: они должны валидировать вход и вызывать сервисы.
- Не тянуть продуктовую логику в aiogram handlers.
- Держать SQL-доступ внутри `storage/`-репозиториев, а не размазывать raw queries по сервисам.
- Сохранять явные границы адаптеров, чтобы будущие `business/fullaccess` режимы не протекали в bot-handlers.
- Предпочитать аддитивные модули вместо разрастания монолитных файлов.
- Использовать bot layer как bridge между `storage/` и будущим digest engine, а не как место для самой digest-логики.

## Ingest pipeline

Текущий ingest MVP устроен так:

- `bot/handlers/ingest.py` принимает `message` и `channel_post`, но не содержит бизнес-логики;
- `services/message_ingest.py` проверяет allowlist, статус источника и пригодность сообщения для digest-контура;
- `services/message_normalizer.py` выделяет `raw_text`, строит предсказуемый `normalized_text`, собирает sender/forward/entities/media-метаданные;
- `storage/repositories.py` делает upsert в `messages` по `(chat_id, telegram_message_id)` и отдаёт агрегаты для `/status` и `/sources`.

Эта цепочка соединяет Telegram bot adapter с `message_store` (`messages` и `messages_fts`) и напрямую питает digest engine MVP на реальных накопленных данных.

## Digest pipeline

Первый реальный digest MVP теперь устроен так:

- `bot/handlers/management.py` подключает `/digest_now`, но сам остаётся тонким;
- `services/digest_window.py` разбирает окно вида `12h`, `24h`, `3d` и фиксирует точные UTC-границы;
- `services/digest_engine.py` оркестрирует весь flow: чтение данных, сборку digest, сохранение в БД и публикацию;
- `services/digest_builder.py` детерминированно группирует сообщения по источникам, отбрасывает шум, частично схлопывает дубли и выбирает наиболее содержательные пункты;
- `services/digest_formatter.py` превращает результат в Telegram-friendly текст и режет его на chunk’и при необходимости;
- `storage/repositories.py` отдаёт сообщения только из активных digest-источников и сохраняет итог в `digests` и `digest_items`.

Ключевой принцип этого слоя: digest вызывается только по локальной SQLite-БД. В момент `/digest_now` бот не читает Telegram напрямую, а работает по уже накопленным данным из `messages`.

## Ближайшее развитие

- Продолжать использовать bot layer для управления allowlist, digest target и ручным запуском digest, пока нет scheduler-слоя.
- Расширять миграции и репозитории постепенно, когда станут реальными workflows для digest/memory/reminders.
- Переиспользовать `messages` и `messages_fts` для будущего поиска, retrieval и digest-selection сценариев.
- Добавлять reminder, memory и reply-модули как отдельные сервисы, а не как код внутри handlers.
