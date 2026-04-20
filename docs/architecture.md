# Заметка по архитектуре

## Назначение

Репозиторий остаётся локальным single-user MVP. Первая полезная ценность — digest-сводки по выбранным Telegram-источникам. Memory, reply suggestions, reminders и расширение провайдеров запланированы, но пока не реализованы как бизнес-логика.

## Зоны ответственности модулей

- `apps/` содержит только runnable entrypoint’ы.
- `bot/` содержит aiogram routing и тонкие Telegram-handlers.
- `bot/` теперь также даёт Telegram-интерфейс для управления allowlist источников и базовыми настройками digest.
- `worker/` содержит точки входа для фонового bootstrap/run-once сценария.
- `services/` содержит прикладную логику, которую вызывают handlers и entrypoint’ы, включая реестр источников, digest target и статусные сводки.
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

## Ближайшее развитие

- Добавить orchestration слоя источников и digest под `services/` с опорой на adapters.
- Продолжать использовать bot layer для управления allowlist и digest target, пока сам digest engine не подключён.
- Расширять миграции и репозитории постепенно, когда станут реальными workflows для digest/memory/reminders.
- Переиспользовать `messages` и `messages_fts` для будущего поиска и retrieval-сценариев.
- Добавлять reminder, memory и reply-модули как отдельные сервисы, а не как код внутри handlers.
