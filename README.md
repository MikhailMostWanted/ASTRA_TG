# Astra AFT

Astra AFT — локальный MVP Telegram-ассистента. Репозиторий уже содержит базовый skeleton проекта:

- `apps/bot` для entrypoint Telegram-бота,
- `apps/worker` для фонового bootstrap/run-once сценария,
- общие границы `config`, `storage`, `services` и `adapters`,
- ingest MVP для накопления входящих сообщений из разрешённых Telegram-источников,
- первый локальный digest MVP без LLM поверх уже сохранённых сообщений.
- первый локальный memory MVP по чатам и людям поверх уже сохранённых сообщений.
- первый локальный reply coach MVP по уже сохранённым сообщениям и memory-картам.
- первый локальный reminders MVP с подтверждением кандидатов и доставкой из worker.
- optional provider layer для безопасного LLM-refine поверх уже существующих deterministic reply и digest пайплайнов.
- experimental full-access scaffold в read-only режиме для ручного sync пользовательской истории в тот же `message_store`.

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

Если нужен experimental full-access transport через Telethon, поставьте optional extra отдельно:

```bash
pip install -e ".[dev,fullaccess]"
```

После editable-установки в активированном `.venv` появляется installable CLI-команда `astratg`.

## CLI `astratg`

Основной локальный operational UX теперь идёт через `astratg`:

```bash
astratg start
astratg status
astratg logs --tail 50
astratg backup
astratg export
astratg stop
```

Что делает CLI:

- `astratg start` поднимает `bot` и фоновый `worker` через текущий Python-интерпретатор активного окружения;
- `astratg stop` останавливает только процессы, запущенные через этот CLI;
- `astratg status` показывает `.env`, состояние `bot/worker`, пути к pid/log, доступность базы и provider;
- `astratg doctor` строит диагностический отчёт поверх существующего operational слоя;
- `astratg backup` и `astratg export` прокидывают уже существующие `apps.ops` команды;
- `astratg logs` показывает лог-файлы из `var/log/` и умеет печатать tail последних строк.

Runtime-файлы CLI:

- `var/run/astra-bot.pid`
- `var/run/astra-worker.pid`
- `var/log/astra-bot.log`
- `var/log/astra-worker.log`

Фоновый `worker` в CLI-режиме не меняет reminder-логику: он просто периодически запускает уже существующий `run_worker_once()` локальным loop-wrapper-ом.

Чтобы вызывать `astratg` из любого терминала на macOS:

- если хочешь использовать именно текущий проектный `.venv`, добавь alias на абсолютный путь к `.venv/bin/astratg`;
- если нужен отдельный глобально доступный wrapper, можно поставить проект через `pipx install --editable /абсолютный/путь/к/ASTRA_TG`.

CLI сам переключается в корень репозитория, поэтому команды можно вызывать не только из каталога проекта.

## Desktop app

В репозитории появился первый desktop-слой для macOS:

- `apps/desktop` — Tauri + React + TypeScript desktop frontend;
- `apps/desktop_api` — тонкий локальный FastAPI bridge поверх уже существующих Python-сервисов;
- desktop не заменяет Telegram-бота, а становится основной удобной панелью управления;
- bot-first flow и текущая Python-логика остаются прежними.

Что уже реально подключено в первой версии desktop:

- dashboard со status cards, activity, warnings и quick actions;
- chats screen со split-layout, сообщениями и live reply preview;
- sources / sync;
- full-access status и ручной local login flow;
- memory, digest, reminders;
- logs / ops basics.

Для desktop dev-режима нужен установленный Node.js и Rust toolchain. Практически лучше держать Node LTS.

Команды:

```bash
astratg desktop-api
astratg desktop
astratg desktop-build
astratg desktop-install
astratg desktop-open
astratg desktop-stop
```

Что делает каждая:

- `astratg desktop-api` поднимает только локальный bridge на `http://127.0.0.1:8765`;
- `astratg desktop` запускает Tauri desktop dev-режим и, если bridge ещё не поднят, стартует его автоматически;
- `astratg desktop-build` собирает локальный `.app` и кладёт его в `var/desktop/Astra Desktop.app`;
- `astratg desktop-install` копирует готовый `.app` в `~/Applications/Astra Desktop.app`;
- `astratg desktop-open` открывает установленный `.app` двойному клику эквивалентно через `open`;
- `astratg desktop-stop` корректно закрывает приложение и останавливает desktop bridge;
- frontend получает API URL через локальное окружение и не ходит напрямую по разрозненным Python-модулям.

Обычный macOS-flow:

```bash
astratg desktop-build
astratg desktop-install
astratg desktop-open
```

Что важно:

- после `astratg desktop-install` приложение лежит в `~/Applications/Astra Desktop.app` и его можно запускать без терминала через Finder, Dock, Launchpad или Spotlight;
- локальная сборка без установки лежит в `var/desktop/Astra Desktop.app`;
- при старте `.app` сам проверяет bridge, поднимает его при необходимости и не плодит второй экземпляр окна;
- если bridge был поднят самим приложением, он завершается при закрытии окна/приложения.

Как удалить:

- закрой приложение через `astratg desktop-stop` или `Cmd+Q`;
- удали `~/Applications/Astra Desktop.app` или `var/desktop/Astra Desktop.app`;
- при желании удали `~/Library/Application Support/Astra Desktop/launcher.json`.

## Provider layer

Deterministic режим остаётся основным и работает даже при полностью пустом LLM-конфиге.

Опциональный provider layer включается только через `.env`:

```env
LLM_ENABLED=true
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
LLM_MODEL_FAST=gpt-4.1-mini
LLM_MODEL_DEEP=gpt-4.1
LLM_TIMEOUT=15
LLM_REFINE_REPLY_ENABLED=true
LLM_REFINE_DIGEST_ENABLED=true
```

`LLM_API_KEY` можно оставить пустым для локальных OpenAI-compatible провайдеров вроде Ollama.

Что важно:

- если `LLM_ENABLED=false`, `/reply` и `/digest_now` продолжают работать как раньше;
- provider не вшит в бизнес-логику и сидит отдельным abstraction layer в `services/providers/`;
- LLM используется только как optional refinement поверх уже собранного deterministic baseline;
- если provider не настроен, недоступен или не проходит guardrails, сервис честно откатывается к локальному результату.

## Experimental full-access scaffold

Bot-first сценарий остаётся основным. Experimental full-access слой не включён по умолчанию, не заменяет основной поток и сейчас работает только как ручной read-only scaffold.

Минимальный `.env` для этого режима:

```env
FULLACCESS_ENABLED=true
FULLACCESS_API_ID=...
FULLACCESS_API_HASH=...
FULLACCESS_SESSION_PATH=./var/fullaccess.session
FULLACCESS_PHONE=+79990000000
FULLACCESS_READONLY=true
FULLACCESS_SYNC_LIMIT=200
```

Что делает этот слой на текущем шаге:

- хранит локальную пользовательскую Telegram-session;
- даёт `/fullaccess_status`, `/fullaccess_login`, `/fullaccess_logout`;
- показывает доступные пользовательские чаты через `/fullaccess_chats`;
- вручную синкает историю одного чата через `/fullaccess_sync <chat_id|@username>`;
- пишет сообщения в те же `chats/messages`, помечая их `source_adapter=fullaccess`;
- при первом sync автоматически регистрирует чат как `category=fullaccess`, `is_enabled=false`, `exclude_from_digest=true`.

Что этот слой принципиально не делает:

- не отправляет сообщения от имени пользователя;
- не редактирует и не удаляет сообщения;
- не ставит реакции;
- не запускает автоответ;
- не крутит фоновые автономные sync/send циклы;
- не заменяет Telegram-клиент.

Если Telegram после кода попросит пароль 2FA, безопасный локальный helper:

```bash
astratg fullaccess status
astratg fullaccess login --code 12345
astratg fullaccess logout
```

## Основные команды

Запуск тестов:

```bash
pytest
```

Высокоуровневый локальный запуск:

```bash
astratg start
astratg start bot
astratg start worker
astratg stop
astratg stop bot
astratg stop worker
astratg restart
astratg status
astratg status bot
astratg status worker
astratg doctor
astratg logs --tail 50
astratg backup
astratg export
astratg desktop-api
astratg desktop
astratg desktop-build
astratg desktop-install
astratg desktop-open
astratg desktop-stop
```

Низкоуровневые entrypoints и ops-утилиты по-прежнему доступны напрямую:

```bash
python -m apps.ops status
python -m apps.ops backup
python -m apps.ops export
python -m apps.worker
python -m apps.bot
```

### Быстрый first-run

После этого шага у бота есть отдельный operational UX слой:

- `/onboarding` — коротко объясняет, что такое Astra AFT и в каком порядке её поднимать.
- `/status` — короткая живая сводка: что уже готово и какой следующий шаг.
- `/checklist` — пошаговая setup-checklist с едиными маркерами `[OK]`, `[WARN]`, `[OPT]`, `[EXP]`, `[OFF]`.
- `/doctor` — диагностика: что в порядке, какие есть предупреждения и что чинить дальше.
- `/help` — команды по разделам, а не просто длинный общий список.

Быстрый порядок запуска теперь такой:

1. Открой личный чат с ботом и отправь `/start` или `/onboarding`.
2. Проверь текущее состояние через `/checklist`.
3. Добавь хотя бы один источник через `/source_add <chat_id|@username>` или посмотри `/sources`.
4. Накопи сообщения или подтяни историю через `/fullaccess_sync <chat_id|@username>`, если используешь experimental слой.
5. При необходимости задай канал доставки через `/digest_target <chat_id|@username>`.
6. Построй память через `/memory_rebuild`.
7. Проверь рабочий контур командами `/digest_now`, `/reply <chat_id|@username>` и `/reminders_scan`.
8. Если что-то не сходится, смотри `/doctor`.

Команды Telegram-бота по разделам:

- Настройка: `/start`, `/onboarding`, `/help`
- Диагностика: `/status`, `/checklist`, `/doctor`, `/settings`
- Источники: `/sources`, `/source_add`, `/source_disable`, `/source_enable`
- Digest: `/digest_target`, `/digest_now`, `/digest_llm`
- Память: `/memory_rebuild`, `/chat_memory`, `/person_memory`
- Ответы: `/reply`, `/reply_llm`, `/examples_rebuild`, `/reply_examples`, `/style_profiles`, `/style_set`, `/style_unset`, `/style_status`, `/persona_status`
- Напоминания: `/reminders_scan`, `/tasks`, `/reminders`
- Provider: `/provider_status`
- Full-access experimental: `/fullaccess_status`, `/fullaccess_login [код]`, `/fullaccess_logout`, `/fullaccess_chats`, `/fullaccess_sync <chat_id|@username>`

`/status` теперь не пытается быть giant log. Он показывает короткую operational сводку: готовность, состояние ключевых слоёв и следующую рекомендуемую команду. Подробности и причины вынесены в `/checklist` и `/doctor`.

## Безопасный ежедневный запуск

Базовый безопасный цикл теперь такой:

1. Запусти `astratg start` и смотри стартовую self-check сводку через `astratg logs --tail 50`.
2. Проверь состояние `astratg status` или `astratg doctor`.
3. Перед ручными экспериментами сделай `astratg backup`.
4. Для компактной диагностики проекта выгрузи `astratg export`.
5. Когда локальный контур больше не нужен, останови его через `astratg stop`.

Что теперь проверяется на старте `apps.bot` и `apps.worker`:

- доступность БД и применённость миграций;
- обязательные env для bot layer;
- состояние provider layer: настроен или честно disabled;
- состояние experimental full-access: готов или честно disabled/not-ready;
- owner chat;
- worker jobs и базовая готовность delivery-контура.

Если критично не хватает конфигурации, entrypoint больше не стартует молча в полуживом состоянии.

## Backup и diagnostic export

`astratg backup`:

- делает локальную timestamped-копию SQLite-базы в `var/backups/`;
- использует штатный SQLite backup API, без небезопасных трюков;
- сохраняет путь последнего backup в operational state;
- внутри прокидывает уже существующий `apps.ops backup`.

`astratg export`:

- пишет компактную JSON-сводку в `var/exports/`;
- показывает количества источников, сообщений, digest, memory cards, reply examples, tasks/reminders;
- добавляет состояние provider/full-access;
- добавляет последние operational timestamps: digest, memory rebuild, reminder delivery, full-access sync, backup, export;
- включает recent errors и startup warnings, если они были;
- внутри прокидывает уже существующий `apps.ops export`.

## Логи и ошибки

Теперь у проекта есть единый structured logging layer:

- startup/boot события для `apps.bot`, `apps.worker`, `storage`;
- ключевые точки `digest`, `reply`, `reminders`, `provider`, `full-access`;
- короткие event names и уровни `info/warning/error`;
- маскирование чувствительных полей вроде token/api key/session.

Handler-ошибки и worker-ошибки больше не должны ронять весь процесс от одного плохого кейса:

- пользователь получает короткое сообщение вроде `Операция не выполнена.`, `Источник не найден.`, `Провайдер сейчас недоступен.`, `full-access не настроен.`;
- в лог уходит реальная причина;
- reminder worker продолжает run даже если один reminder сломался;
- recent errors и startup warnings попадают в `/doctor` и operational export.

## Типичные проблемы

- `TELEGRAM_BOT_TOKEN не задан`: bot не стартует, проверь `.env`.
- `Provider layer не готов`: deterministic fallback останется рабочим, детали смотри в `/provider_status` и `/doctor`.
- `Experimental full-access не готов`: это не ломает bot-first контур, смотри `/fullaccess_status`.
- `owner chat пока неизвестен`: открой личный чат с ботом и отправь `/start`.
- `reminders некуда доставлять` или worker warning: проверь owner chat и запуск `python -m apps.worker`.
- Нужен быстрый срез состояния без чтения БД руками: используй `python -m apps.ops export`.

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
- `/digest_llm` использует тот же локальный pipeline, а затем при доступном provider может чуть улучшить `summary_short`, overview и key-source wording;
- source of truth по данным остаётся в локальной БД и deterministic builder, provider не должен придумывать новые события.

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

Теперь поверх `messages`, `chat_memory` и `people_memory` подключён первый локальный reply coach без внешних LLM, с реальным style layer, первым owner persona layer и локальным few-shot retrieval layer:

- `/reply <chat_id|@username>` работает только по локальной SQLite-БД и уже сохранённым сообщениям;
- движок берёт последние 20–40 сообщений, память по чату и связанным людям, а затем выбирает один лучший draft-ответ;
- reply layer остаётся эвристическим и детерминированным: без OpenAI, Anthropic и локальных моделей;
- поверх базового draft теперь работает отдельный style layer с встроенными профилями и chat-specific override;
- поверх style layer теперь сидит отдельный owner persona core с детерминированным enrichment и guardrails;
- поверх локальной истории теперь сидит и отдельный few-shot retrieval layer: он собирает пары `входящий контекст -> мой реальный ответ`, хранит их в `reply_examples` и подмешивает похожие примеры в `/reply` как дополнительную опору;
- текущая цель слоя — не style cloning и не personality mining, а безопасный управляемый Telegram-ответ с понятной причиной выбора;
- в ответе бот показывает стиль, факт применения persona, наличие few-shot support, итоговую серию сообщений, краткое объяснение, риск и уверенность.
- `/reply_llm` сначала строит тот же deterministic baseline, а потом при доступном provider может мягко refine-ить формулировку поверх готовой серии;
- если provider недоступен или LLM-кандидат не проходит guardrails, бот честно сообщает про fallback и оставляет локальный deterministic ответ.

Что умеет reply engine на этом шаге:

- различать вопрос/уточнение, просьбу, лёгкий бытовой разговор, напряжённый фрагмент и ситуацию, где лучше не отвечать сразу;
- опираться на `chat_memory.current_state`, `pending_tasks`, `recent_conflicts`, `people_memory.interaction_pattern` и `open_loops`;
- выбирать effective style-профиль по ручному override или простому fallback из памяти;
- превращать базовый draft не только в одну строку, а в серию из 1–4 коротких Telegram-сообщений;
- дополнительно прогонять style-aware серию через owner persona core, чтобы ответ звучал ближе к владельцу по ритму, объяснению и ограничениям;
- находить несколько похожих прошлых реальных ответов владельца по локальной БД и использовать их как объяснимую few-shot опору без копипаста и без embeddings;
- показывать `persona_notes`, guardrail-флаги и финальную persona-aware серию в preview;
- честно говорить, если чата нет, данных пока мало или последнее сохранённое сообщение уже от пользователя.

### Few-shot retrieval layer

Что делает локальный few-shot слой на этом шаге:

- `/examples_rebuild` пересобирает `reply_examples` только по локальной SQLite-БД;
- builder спокойно извлекает пары `последний inbound -> ближайший outbound владельца` в разумном окне времени;
- мусорные короткие сообщения, сервисные команды и слабые пары отсекаются простыми эвристиками и `quality_score`;
- retrieval идёт детерминированно через SQLite FTS5 по `inbound_normalized`, а затем усиливается бонусами за тот же чат, того же человека, тип ситуации, свежесть и качество;
- `/reply_examples` показывает, какие локальные примеры реально были найдены и почему они попали в top-k;
- `/reply` использует few-shot слой только как guidance для стратегии, уверенности, длины и ритма, но не копирует прошлый ответ целиком.

## Reminder MVP

Теперь поверх локальной БД подключён первый реальный reminder/task flow без LLM:

- `/reminders_scan` читает только уже сохранённые `messages` из активных источников;
- источники с `exclude_from_memory = true` в scan не участвуют;
- extractor работает детерминированно и ищет прозрачные сигналы вроде `напомни`, `не забудь`, `созвонимся`, `скину`, `надо`, `дедлайн`, `HH:MM`, `завтра`, `через час`, `вечером`;
- scan не создаёт активные reminders молча: бот показывает candidate-card с inline-кнопками `Одобрить`, `Отменить`, `Позже`;
- после подтверждения сущности сохраняются в `tasks` и `reminders`, а worker доставляет due reminders в `bot.owner_chat_id`.

Поддержанные сценарии:

- `/reminders_scan`
- `/reminders_scan 24h`
- `/reminders_scan 3d`
- `/reminders_scan @mychannel`
- `/tasks`
- `/reminders`

### Как получить первое рабочее напоминание

1. Запусти бота и напиши ему в личку хотя бы `/start` или `/status`, чтобы сохранился `bot.owner_chat_id`.
2. Добавь нужный источник через `/source_add <chat_id|@username>`.
3. Накопи в разрешённом источнике сообщения с явными reminder-сигналами.
4. Вызови `/reminders_scan` или `/reminders_scan 24h`.
5. Подтверди найденную карточку кнопкой `Одобрить` или `Позже`.
6. Запусти worker через `python -m apps.worker`, когда reminder станет due.
7. Проверь `/tasks`, `/reminders` и `/status`.

### Style layer MVP

Встроенные style-профили:

- `base`
- `friend_hard`
- `friend_explain`
- `romantic_soft`
- `practical_short`
- `tension_soft`

Что делает style layer на этом шаге:

- хранит встроенные профили в отдельной таблице `style_profiles`;
- хранит ручные chat-specific override отдельно в `chat_style_overrides`;
- выбирает effective profile спокойно и предсказуемо: override -> явный fallback из памяти -> `base`;
- детерминированно режет базовый draft на серию коротких сообщений, снижает лишнюю пунктуацию и делает ответ более Telegram-friendly;
- не использует внешние LLM и не пытается делать идеальный personality clone.

### Persona layer MVP

Что делает owner persona layer на этом шаге:

- хранит `persona.core`, `persona.guardrails`, `persona.enabled` и `persona.version` в `settings`;
- отделяет owner persona core от style profile: стиль отвечает за режим, persona — за общую манеру владельца;
- детерминированно поджимает слишком гладкие формулировки, усиливает короткий телеграмный ритм и не даёт ответу уехать в карикатуру;
- прогоняет результат через отдельные guardrails: длина, литературность, ботскость, шумная пунктуация, перегруз грубостью и повтор opener’ов;
- даёт служебную команду `/persona_status` для проверки состояния persona слоя.

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
- Для few-shot слоя добавлены `reply_examples`, `reply_examples_fts` и отдельные триггеры синхронизации FTS.
- Сервисный ingest находится в `services/message_ingest.py`, а нормализация входящих сообщений — в `services/message_normalizer.py`.
- Memory-сервисы лежат в `services/memory_builder.py`, `services/chat_memory_builder.py`, `services/people_memory_builder.py` и `services/memory_formatter.py`.
- Reply-сервисы лежат в `services/reply_context_builder.py`, `services/reply_classifier.py`, `services/reply_strategy.py`, `services/reply_engine.py` и `services/reply_formatter.py`.
- Few-shot reply-сервисы лежат в `services/reply_examples_builder.py`, `services/reply_examples_retriever.py`, `services/reply_examples_formatter.py` и `services/reply_examples_models.py`.
- Reminder-сервисы лежат в `services/reminder_extractor.py`, `services/reminder_service.py`, `services/reminder_formatter.py` и `services/reminder_delivery.py`.
- Persona-сервисы лежат в `services/persona_rules.py`, `services/persona_core.py`, `services/persona_adapter.py`, `services/persona_guardrails.py` и `services/persona_formatter.py`.

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
- первый детерминированный style layer с профилями и chat-specific override,
- первый owner persona core поверх style layer с guardrails и `/persona_status`,
- первый детерминированный reminder extraction layer с candidate-card и worker delivery,
- тонкая обвязка bot/worker,
- первая реальная миграция локальной схемы хранения.

Пока намеренно не реализованы:

- внешний provider layer для reply,
- style cloning личности,
- автоответ или one-tap send,
- закрытие задач, повторяющиеся reminders и календарная интеграция,
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

5. При необходимости назначь конкретный стиль:

- `/style_profiles`
- `/style_set @mychannel friend_explain`
- `/style_status @mychannel`

6. Получи первую подсказку ответа:

- `/reply @mychannel`
- `/reply -1001234567890`

Бот покажет:

- какой чат анализировался;
- на какое последнее сообщение он ориентировался;
- какой style-профиль применился;
- серию коротких сообщений вместо одного длинного абзаца;
- краткое объяснение выбора;
- риск и уверенность.

Если данных пока мало, бот честно скажет об этом и не будет придумывать reply из воздуха.

## Как проверить ingest, memory, reply, reminders и digest вручную

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

9. Проверь reminders:

- вызови `/reminders_scan` или `/reminders_scan 24h`;
- подтверди candidate-card через inline-кнопку;
- проверь `/tasks` и `/reminders`;
- затем запусти `python -m apps.worker` и дождись due reminder packet в личке бота.

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

Проверка задач и reminders:

```bash
sqlite3 var/astra.db "SELECT id, source_chat_id, source_message_id, title, status, due_at, suggested_remind_at, needs_user_confirmation FROM tasks ORDER BY id DESC LIMIT 10;"
sqlite3 var/astra.db "SELECT id, task_id, remind_at, status, last_notification_at FROM reminders ORDER BY id DESC LIMIT 10;"
```
