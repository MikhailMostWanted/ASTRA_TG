# Заметка по архитектуре

## Назначение

Репозиторий остаётся локальным single-user MVP. Первая полезная ценность — digest-сводки, memory-карты и reply coach по выбранным Telegram-источникам. Reply слой уже подключён как локальный эвристический сервис: сначала safe draft, потом style layer, а теперь ещё и детерминированный owner persona layer с guardrails. Provider layer, deeper few-shot persona и reminders остаются следующими шагами.

## Зоны ответственности модулей

- `apps/` содержит только runnable entrypoint’ы.
- `bot/` содержит aiogram routing и тонкие Telegram-handlers.
- `bot/` теперь также даёт Telegram-интерфейс для управления allowlist источников, базовыми настройками digest и приёма входящих updates для ingest.
- `worker/` содержит точки входа для фонового bootstrap/run-once сценария.
- `services/` содержит прикладную логику, которую вызывают handlers и entrypoint’ы, включая реестр источников, digest target, ingest pipeline, digest engine, memory builders, reply engine, style layer, persona layer и статусные сводки.
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
- Memory слой строить только поверх уже сохранённых `messages` и `chats`, без прямого чтения Telegram в момент rebuild.
- Расширять миграции и репозитории постепенно, когда станут реальными workflows для digest/memory/reminders.
- Переиспользовать `messages` и `messages_fts` для будущего поиска, retrieval и digest-selection сценариев.
- Добавлять reminder, memory и reply-модули как отдельные сервисы, а не как код внутри handlers.

## Memory pipeline

Первый реальный memory MVP теперь устроен так:

- `bot/handlers/management.py` подключает `/memory_rebuild`, `/chat_memory` и `/person_memory`, но не содержит memory-логики;
- `services/memory_builder.py` оркестрирует rebuild, обновляет `chat_memory` и `people_memory`, а также даёт bot-friendly чтение карточек;
- `services/chat_memory_builder.py` детерминированно собирает карточку чата по локальным сообщениям, темам, участникам, открытым хвостам и конфликтным сигналам;
- `services/people_memory_builder.py` детерминированно собирает карточки людей по `sender_id`, `sender_name` и контексту чатов;
- `services/memory_formatter.py` превращает JSON-поля memory в короткие Telegram-friendly карточки;
- `storage/repositories.py` даёт upsert/get/search/count API для `chat_memory`, `people_memory` и нужных message-агрегатов.

Ключевой принцип этого слоя: память строится только по локальной SQLite-БД и остаётся честной, предсказуемой и полностью детерминированной. Это подготовительный слой под будущие reply suggestions, а не попытка сделать “умную” persona-модель на эвристиках.

## Reply pipeline

Первый рабочий reply MVP теперь устроен так:

- `bot/handlers/management.py` подключает `/reply`, но сам остаётся тонким;
- `services/reply_context_builder.py` собирает reply-context только из локальной БД: последние сообщения чата, `chat_memory`, связанный `people_memory`, признаки открытых хвостов и конфликтов;
- `services/reply_classifier.py` определяет тип ситуации простыми эвристиками: вопрос, просьба, лёгкий бытовой обмен, напряжённый фрагмент или сценарий, где лучше не отвечать сразу;
- `services/reply_strategy.py` выбирает безопасную стратегию ответа и формирует базовый safe draft;
- `services/style_selector.py` выбирает effective style-профиль по ручному override или по простому fallback из memory;
- `services/style_adapter.py` детерминированно превращает базовый draft в серию коротких сообщений;
- `services/persona_core.py` загружает owner persona core и guardrails из `settings`;
- `services/persona_adapter.py` мягко обогащает style-aware серию owner-like ритмом, связками и ограничениями;
- `services/persona_guardrails.py` проверяет длину, литературность, шумную пунктуацию, грубость и карикатурные паттерны;
- `services/reply_engine.py` оркестрирует весь flow и возвращает структурированный persona-aware результат;
- `services/reply_formatter.py` превращает его в Telegram-friendly сообщение для `/reply`;
- `storage/repositories.py` даёт минимальные выборки и агрегаты для reply readiness, style profiles, chat overrides, `settings` и связанных memory-карт.

Ключевой принцип этого слоя: reply suggestions строятся только по локальным `messages + chat_memory + people_memory`, а style/persona adaptation остаётся полностью структурированной и детерминированной. Здесь нет внешних LLM, автоматического обучения на всём архиве, магического style cloning или автоответа. Текущий owner persona core — это управляемая база под будущий deeper persona / few-shot layer, а не попытка сразу сделать full personality clone.

## Style layer

Первый style layer теперь устроен так:

- `style_profiles` хранит встроенные профили с явными структурированными признаками;
- `chat_style_overrides` хранит ручное переопределение профиля для уже известных `chats`;
- `/style_profiles`, `/style_set`, `/style_unset`, `/style_status` работают только по зарегистрированным в allowlist чатам и не смешиваются с source discovery;
- fallback-селектор остаётся спокойным: `override` -> явный сигнал из памяти -> `base`;
- adapter меняет только форму ответа: серия коротких сообщений, ритм, пунктуация, opener/closer, но не пытается делать опасную имитацию личности.

## Persona layer

Первый owner persona layer теперь устроен так:

- `settings` хранит `persona.core`, `persona.guardrails`, `persona.enabled` и `persona.version`;
- persona core описывает общие правила владельца: речь, объяснение, тепло, прямоту, ограничения на грубость, anti-pattern’ы, opener/closer bank и rewrite constraints;
- style profile остаётся ответом на вопрос "в каком режиме говорить", а persona core — ответом на вопрос "как в целом звучит владелец проекта";
- enrichment идёт только поверх style-aware серии и работает мягко: если ответ уже звучит нормально, persona слой не должен его уродовать;
- guardrails при сомнительном результате откатывают ответ к более безопасной style-aware версии;
- `/persona_status` даёт наблюдаемость по активному core, guardrails и anti-pattern ограничениям.
