# Заметка по архитектуре

## Назначение

Репозиторий остаётся локальным single-user MVP. Первая полезная ценность — digest-сводки, memory-карты, reply coach и reminders по выбранным Telegram-источникам. Reply слой уже подключён как локальный эвристический сервис: сначала safe draft, потом style layer, затем детерминированный owner persona layer с guardrails, а теперь ещё и локальный few-shot retrieval layer поверх реальных прошлых ответов владельца. Reminder слой тоже уже подключён как локальный детерминированный pipeline: scan по сохранённым сообщениям, подтверждение кандидатов и доставка due reminders через worker. Поверх этих deterministic пайплайнов теперь добавлен optional provider layer: он не меняет source of truth и не обязателен для работы проекта.

## Зоны ответственности модулей

- `apps/` содержит только runnable entrypoint’ы.
- `bot/` содержит aiogram routing и тонкие Telegram-handlers.
- `bot/` теперь также даёт Telegram-интерфейс для управления allowlist источников, базовыми настройками digest и приёма входящих updates для ingest.
- `worker/` содержит точки входа для фонового bootstrap/run-once сценария.
- `services/` содержит прикладную логику, которую вызывают handlers и entrypoint’ы, включая реестр источников, digest target, ingest pipeline, digest engine, memory builders, reply engine, style layer, persona layer, local few-shot retrieval layer, reminder extraction/delivery, provider layer и статусные сводки.
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
- Provider layer держать отдельным и опциональным: никаких прямых вызовов конкретного вендора из reply/digest бизнес-логики.

## Provider layer

Provider layer устроен как отдельный верхний слой над уже существующими deterministic пайплайнами:

- `services/providers/base.py` задаёт минимальный контракт для short-form rewrite и structured digest improvement задач;
- `services/providers/models.py` хранит типы задач, prompt/request/response модели и provider status;
- `services/providers/factory.py` и `services/providers/manager.py` собирают runtime, знают про `LLM_ENABLED`, выбранный provider, модели, runtime-статус и graceful fallback;
- `services/providers/openai_compatible.py` даёт один HTTP-адаптер под OpenAI-compatible `/chat/completions`;
- `services/providers/prompts.py` строит короткие и жёсткие prompt’ы без giant prompt spaghetti;
- `services/providers/guardrails.py` проверяет, что refine-кандидаты не уезжают в литературщину, не добавляют факты и не ломают Telegram-ритм;
- `services/providers/reply_refiner.py` и `services/providers/digest_refiner.py` встраивают provider только как optional refinement поверх уже готового baseline.

Ключевой принцип этого слоя: baseline truth остаётся в локальной SQLite-БД, deterministic builder’ах и локальных guardrails. Provider может только улучшить wording. Если он не настроен, упал или отдал плохой candidate, сервис обязан откатиться к baseline.

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
- тот же handler теперь даёт и `/digest_llm`, который вызывает тот же deterministic pipeline и только потом optional provider refine;
- `services/digest_window.py` разбирает окно вида `12h`, `24h`, `3d` и фиксирует точные UTC-границы;
- `services/digest_engine.py` оркестрирует весь flow: чтение данных, сборку digest, сохранение в БД и публикацию;
- `services/digest_builder.py` детерминированно группирует сообщения по источникам, отбрасывает шум, частично схлопывает дубли и выбирает наиболее содержательные пункты;
- `services/digest_formatter.py` превращает результат в Telegram-friendly текст и режет его на chunk’и при необходимости;
- `storage/repositories.py` отдаёт сообщения только из активных digest-источников и сохраняет итог в `digests` и `digest_items`.

Ключевой принцип этого слоя: digest вызывается только по локальной SQLite-БД. В момент `/digest_now` и `/digest_llm` бот не читает Telegram напрямую, а работает по уже накопленным данным из `messages`. Даже в LLM-assisted режиме provider меняет только wording `summary_short`, overview и key-source блоков; данные и детали по источникам остаются локальными.

## Reminder pipeline

Первый рабочий reminder MVP теперь устроен так:

- `bot/handlers/reminders.py` подключает `/reminders_scan`, `/tasks`, `/reminders` и callback flow для inline-кнопок;
- `services/reminder_window.py` разбирает scan-окна вида `24h` и `3d`;
- `services/reminder_extractor.py` детерминированно ищет сигналы задач и reminders только по локальным сообщениям, без LLM;
- `services/reminder_service.py` оркестрирует scan, сохранение candidate task/reminder, approve/reject/postpone и выдачу списков;
- `services/reminder_formatter.py` отвечает за candidate-card, списки, callback payload и reminder packet;
- `services/reminder_delivery.py` используется worker’ом, чтобы взять due reminders, отправить packet в `bot.owner_chat_id` и перевести reminder в доставленное состояние;
- `storage/repositories.py` теперь даёт отдельные репозитории для `tasks` и `reminders`, а также выборки сообщений под reminder scan.

Ключевой принцип этого слоя: напоминания строятся только по локальной SQLite-БД и никогда не создаются как боевые silently. Сначала пользователь видит candidate-card и явно подтверждает её через inline-кнопку.

## Ближайшее развитие

- Продолжать использовать bot layer для управления allowlist, digest target и reminders, пока нет scheduler-слоя.
- Memory слой строить только поверх уже сохранённых `messages` и `chats`, без прямого чтения Telegram в момент rebuild.
- Расширять reminder-эвристики и сценарии закрытия задач постепенно, без попытки делать “идеальный planner”.
- Переиспользовать `messages` и `messages_fts` для будущего поиска, retrieval и digest-selection сценариев.
- Добавлять новые workflows как отдельные сервисы, а не как код внутри handlers.

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

- `bot/handlers/management.py` подключает `/reply` и `/reply_llm`, но сам остаётся тонким;
- `services/reply_context_builder.py` собирает reply-context только из локальной БД: последние сообщения чата, `chat_memory`, связанный `people_memory`, признаки открытых хвостов и конфликтов;
- `services/reply_classifier.py` определяет тип ситуации простыми эвристиками: вопрос, просьба, лёгкий бытовой обмен, напряжённый фрагмент или сценарий, где лучше не отвечать сразу;
- `services/reply_strategy.py` выбирает безопасную стратегию ответа и формирует базовый safe draft;
- `services/reply_examples_builder.py` собирает структурированные пары `inbound -> outbound` в `reply_examples` по локальной истории;
- `services/reply_examples_retriever.py` делает детерминированный top-k поиск по `reply_examples_fts` и добавляет explainable бонусы за тот же чат, того же человека, тип ситуации, свежесть и качество;
- `services/reply_examples_formatter.py` отвечает за наблюдаемость few-shot слоя в `/reply_examples` и служебных preview;
- `services/style_selector.py` выбирает effective style-профиль по ручному override или по простому fallback из memory;
- `services/style_adapter.py` детерминированно превращает базовый draft в серию коротких сообщений;
- `services/persona_core.py` загружает owner persona core и guardrails из `settings`;
- `services/persona_adapter.py` мягко обогащает style-aware серию owner-like ритмом, связками и ограничениями;
- `services/persona_guardrails.py` проверяет длину, литературность, шумную пунктуацию, грубость и карикатурные паттерны;
- `services/reply_engine.py` оркестрирует весь flow и возвращает структурированный persona-aware результат с few-shot support;
- `services/providers/reply_refiner.py` может дополнительно refine-ить финальную серию поверх готового baseline, но только через provider manager и с обязательным fallback;
- `services/reply_formatter.py` превращает его в Telegram-friendly сообщение для `/reply`;
- `storage/repositories.py` даёт минимальные выборки и агрегаты для reply readiness, style profiles, chat overrides, `settings` и связанных memory-карт.

Ключевой принцип этого слоя: reply suggestions строятся только по локальным `messages + chat_memory + people_memory + reply_examples`, а style/persona/few-shot adaptation остаётся полностью структурированной и детерминированной. Здесь нет обязательного внешнего LLM, автоматического обучения на всём архиве, embeddings, vector DB, магического style cloning или автоответа. Few-shot слой — это объяснимый retrieval MVP, который готовит базу под provider-aware reply layer, но сам остаётся локальным и безопасным. `/reply_llm` лишь мягко улучшает wording поверх уже построенного baseline и обязан откатываться назад при любой проблеме.

## Few-shot retrieval layer

Локальный few-shot слой устроен так:

- `reply_examples` хранит не полный дамп чатов, а только выделенные пары `входящий контекст -> реальный исходящий ответ владельца`;
- builder берёт последнее содержательное входящее сообщение и ближайший содержательный исходящий ответ владельца в том же чате, если между ними нет слишком большого разрыва;
- слабые пары отрезаются простыми правилами: пустой текст, короткий шум, сервисные команды, слишком длинные простыни и низкий `quality_score`;
- поиск идёт детерминированно через SQLite FTS5 по `inbound_normalized`, затем результаты ранжируются локальными бонусами за тот же чат, того же человека, тип ситуации, свежесть и качество;
- `/reply_examples` показывает найденные пары человеку в читаемом виде, без JSON blob;
- `/reply` использует few-shot слой только как guidance для выбора тона, длины, ритма и уверенности, но не копирует старый ответ побуквенно.

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
