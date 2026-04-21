# Astra AFT Telegram UX/UI Master Spec

Статус: master-spec для следующего этапа реализации Telegram-интерфейса.

Основание документа: `origin/main` на коммите `5fc1e3c8f4443f6c9962c5d574bdd52f876397f0`, изучены реальные handlers, services, tests и текущие formatter-паттерны.

Важно:

- Этот документ опирается только на уже существующие возможности репозитория.
- Здесь не добавляются новые продуктовые контуры, веб-интерфейс, auto-reply, hidden automation или full-access write-операции.
- `/setup` в текущем репозитории как отдельная команда ещё не существует. В этом master-spec `/setup` описан как будущий навигационный entrypoint поверх уже существующих команд и данных, без новой бизнес-логики.
- `ops / backup / export` сейчас существуют как CLI-утилиты `python -m apps.ops ...`, а не как Telegram-команды. В Telegram UX они описаны как read-only раздел до появления отдельных обработчиков бота.

## 1. Что реально существует в проекте

### 1.1 Реальные Telegram-команды

| Раздел | Команды |
|---|---|
| Первый вход | `/start`, `/onboarding`, `/help` |
| Диагностика | `/status`, `/checklist`, `/doctor`, `/settings` |
| Источники | `/sources`, `/source_add`, `/source_disable`, `/source_enable` |
| Digest | `/digest_target`, `/digest_now`, `/digest_llm` |
| Memory | `/memory_rebuild`, `/chat_memory`, `/person_memory` |
| Reply | `/reply`, `/reply_llm`, `/examples_rebuild`, `/reply_examples`, `/style_profiles`, `/style_set`, `/style_unset`, `/style_status`, `/persona_status` |
| Reminders | `/reminders_scan`, `/tasks`, `/reminders` |
| Provider | `/provider_status` |
| Full-access experimental | `/fullaccess_status`, `/fullaccess_login [код]`, `/fullaccess_logout`, `/fullaccess_chats`, `/fullaccess_sync <chat_id\|@username>` |

### 1.2 Реальные не-командные сценарии

- Passive ingest: бот сохраняет входящие `message` и `channel_post` только из allowlist-источников.
- Owner chat binding: при сообщении в личном чате сохраняется `bot.owner_chat_id`.
- Reminder callback flow: единственный существующий inline-callback сценарий, `reminder:approve`, `reminder:reject`, `reminder:postpone`.
- Worker delivery: due reminders доставляются через `apps.worker`.
- Ops: `python -m apps.ops status`, `python -m apps.ops backup`, `python -m apps.ops export`.

### 1.3 Реальные пользовательские сценарии

1. Открыть личный чат с ботом и привязать owner chat через `/start`.
2. Пройти first-run контур через `/onboarding`, `/status`, `/checklist`, `/doctor`.
3. Добавить источники вручную по `@username`, `chat_id`, форварду или reply-сообщению.
4. Накопить локальные сообщения bot-first ingest’ом или вручную подтянуть историю через experimental full-access sync.
5. Настроить канал доставки digest.
6. Собрать memory-карты по чатам и людям.
7. Получить reply suggestion по локальному контексту, few-shot, style и persona.
8. Построить reminders candidates, подтвердить их inline-кнопками, затем получать delivery через worker.
9. Проверять optional provider layer и experimental full-access layer.
10. Делать backup/export через CLI и видеть их состояние в operational UX.

## 2. Главная идея интерфейса Astra AFT

Astra AFT должен ощущаться не как “чат-бот с кучей команд”, а как спокойная Telegram-first оболочка управления над локальным пайплайном:

- источники и ingest;
- digest;
- memory;
- reply coach;
- reminders;
- provider как optional refinement;
- full-access как experimental мост только для чтения;
- операционный self-check вокруг всего этого.

Главный UX-принцип: пользователь не должен помнить весь набор команд. Он должен попадать в один внятный центр настройки, видеть текущую готовность системы, понимать следующий рекомендуемый шаг и идти по интерфейсу кнопками и короткими карточками, а не через ручной перебор slash-команд.

## 3. Как пользователь должен ощущать проект

Пользователь должен ощущать Astra AFT так:

- спокойно;
- собранно;
- технологично;
- без магии и без притворства;
- как надёжный локальный инструмент, который честно показывает готовность и ограничения;
- как систему, где каждое действие имеет ясный результат и ясный следующий шаг.

Не должно быть ощущения:

- giant command dump;
- “умного ассистента”, который скрывает важные условия;
- панели администратора;
- маркетингового тона;
- noisy Telegram-спама;
- UI, который заставляет вспоминать синтаксис вместо ведения по сценариям.

## 4. Telegram-first принципы интерфейса

1. Один экран = одно сообщение.
2. Навигационные экраны в личном чате лучше редактировать в месте через callback, а не плодить новые сообщения.
3. Результаты действий, которые пользователь может перечитывать отдельно, должны приходить новыми сообщениями.
4. Inline-кнопки нужны для перемещения по разделам и безопасных явных действий, а не для скрытой автоматизации.
5. Пустое состояние всегда должно объяснять, почему данных нет, и давать один понятный следующий шаг.
6. Предупреждение должно говорить, что не так, чем это мешает и что делать дальше.
7. Success-состояние должно фиксировать, что именно изменилось.
8. Короткие блоки сводки важнее длинных списков.
9. На мобильном экране приоритет у 5-8 смысловых строк, а не у полотна текста.
10. Optional и experimental слои должны быть визуально отделены от основного happy path.

## 5. Базовые ограничения продукта, которые интерфейс обязан уважать

- Основной режим продукта: `bot-first`.
- Provider не обязателен. Если он выключен, система всё равно считается рабочей.
- Full-access не обязателен. Если он выключен, система всё равно считается рабочей.
- Full-access сейчас только для чтения.
- Нет auto-reply.
- Нет скрытых фоновых sync/send/edit/delete/reaction сценариев в full-access.
- Reply и digest строятся по локальной SQLite-БД, а не живым походом в Telegram при каждом запросе.
- Reminder candidate должен быть явно подтверждён пользователем.
- `ops backup/export` пока не Telegram-actions.

## 6. Рекомендуемая информационная архитектура

### 6.1 Верхний уровень

Интерфейс должен иметь один центральный вход:

- `Центр настройки` как домашний операционный экран.

Далее от него расходятся разделы:

- Статус
- Checklist
- Doctor
- Источники
- Digest
- Memory
- Reply
- Reminders
- Provider
- Full-access
- Ops

### 6.2 Что такое `/setup`

`/setup` не должен становиться новой бизнес-функцией. Это должен быть alias-вход в `Центр настройки`, который:

- показывает готовность системы;
- показывает следующий рекомендуемый шаг;
- даёт кнопочную навигацию в реальные разделы;
- объединяет уже существующие операционные данные из `/status`, `/checklist`, `/doctor`, `/sources`, `/provider_status`, `/fullaccess_status`;
- не создаёт новых доменных сущностей и не меняет бизнес-логику.

### 6.3 Приоритеты навигации

Основной путь:

1. `/start`
2. `/setup` или `/onboarding`
3. `Источники`
4. `Digest target`
5. `Memory`
6. `Reply`
7. `Reminders`

Боковые ветки:

- `Provider`
- `Full-access`
- `Ops`

## 7. Recommended Next Step Logic

Единая логика рекомендаций должна строиться поверх уже существующего `SystemReadinessService`.

Порядок рекомендаций:

1. Если `owner chat` не сохранён, рекомендовать `/start`.
2. Если нет активных источников, рекомендовать `/source_add`.
3. Если источники есть, но сообщений нет, рекомендовать накопить сообщения или использовать `/fullaccess_sync`.
4. Если не задан digest target, рекомендовать `/digest_target`.
5. Если memory-карты ещё не построены, рекомендовать `/memory_rebuild`.
6. Если reply ещё не готов, рекомендовать `/reply <chat_id|@username>`.
7. Если reminders ещё не проверены, рекомендовать `/reminders_scan`.
8. Если основной путь готов, рекомендовать один из рабочих сценариев: `/digest_now`, `/reply`, `/reminders_scan`.
9. Provider и full-access не должны ломать основной next-step flow, если пользователь их не использует.

UI-правило:

- На каждом экране должен быть один `главный следующий шаг`.
- Этот шаг должен быть коротким, конкретным и executable.
- Если шаг требует аргумент, интерфейс должен либо дать быстрый выбор по уже известным чатам, либо показать краткий формат команды.

## 8. Модель навигации и callback flow

### 8.1 Типы экранов

1. `Навигационные экраны`
   Это `/setup`, `/status`, `/checklist`, `/doctor`, обзорные экраны разделов.
   Их нужно редактировать в месте через callback.

2. `Результаты действий`
   Это digest output, reply suggestion, memory card, reply examples, full-access sync result.
   Их лучше отправлять отдельным сообщением, чтобы не потерять результат.

3. `Action cards`
   Это reminders candidate card и отдельные warning/success карточки.
   Они могут редактироваться по callback после действия.

### 8.2 Глобальный callback-паттерн

Нужны два класса callback-маршрутов:

- навигационные callback-маршруты;
- action callback-маршруты.

Навигационные callback-маршруты:

- `ux:home`
- `ux:setup`
- `ux:status`
- `ux:checklist`
- `ux:doctor`
- `ux:sources`
- `ux:digest`
- `ux:memory`
- `ux:reply`
- `ux:reminders`
- `ux:provider`
- `ux:fullaccess`
- `ux:ops`
- `ux:refresh:<screen>`
- `ux:back:<screen>`

Callback-маршруты выбора поверх существующих сценариев:

- `ux:sources:open:<chat_ref>`
- `ux:sources:disable:<chat_ref>`
- `ux:sources:enable:<chat_ref>`
- `ux:digest:run:<window>`
- `ux:digest:target:help`
- `ux:memory:chat:<chat_ref>`
- `ux:reply:chat:<chat_ref>`
- `ux:reply:examples:<chat_ref>`
- `ux:style:status:<chat_ref>`
- `ux:fullaccess:chat:<chat_ref>`

Существующие action callbacks, которые нужно сохранить без изменения смысла:

- `reminder:approve:<task_id>`
- `reminder:reject:<task_id>`
- `reminder:postpone:<task_id>`

### 8.3 Callback-принцип

- Навигационные callback-маршруты не должны иметь скрытых side effects.
- Action callback-маршруты должны быть явными и обратимыми там, где это уже предусмотрено логикой.
- Для destructive или risky действий в тексте карточки должен быть отдельный warning-блок.

## 9. Визуальная система Telegram-интерфейса

### 9.1 Иерархия заголовков

У карточки должно быть три уровня структуры:

- `Уровень 1`: название экрана, одна строка.
- `Уровень 2`: блок сводки, 2-5 строк.
- `Уровень 3`: секции карточки с короткими подзаголовками.

Рекомендуемый паттерн заголовка:

```text
Astra AFT / Status
```

или

```text
Astra AFT / Reply / Команда продукта
```

### 9.2 Summary blocks

Блок сводки должен быть самым верхним блоком почти на каждом экране.

Что туда входит:

- текущий статус раздела;
- один ключевой числовой факт;
- один главный следующий шаг.

Пример формы:

```text
Сводка
Готовность: 5/9
Следующий шаг: настроить digest target
```

### 9.3 Маркеры статуса

Нужна единая текстовая маркировка:

- `[OK]` — всё готово или безопасно.
- `[WARN]` — не блокирует полностью, но требует внимания.
- `[ERR]` — блокер или нерабочее состояние.
- `[OPT]` — optional слой.
- `[EXP]` — experimental слой.
- `[OFF]` — слой сознательно выключен.

Важно:

- не смешивать стиль маркеров;
- не заменять их случайными эмодзи;
- статус всегда показывать в первых 5-6 строках карточки.

### 9.4 CTA-кнопки

Правило CTA:

- в первом ряду один главный CTA;
- во втором ряду 1-2 соседних действия;
- служебный ряд всегда отдельно.

Первичный CTA должен вести к следующему рекомендуемому шагу.

### 9.5 Secondary actions

Secondary actions нужны для:

- соседних разделов;
- справочного режима;
- rerun или refresh;
- быстрый выбор по существующим чатам.

Они не должны спорить с основным CTA.

### 9.6 Паттерн `Назад / Домой / Обновить`

Это глобальный нижний ряд почти для всех обзорных экранов разделов:

- `Назад`
- `Домой`
- `Обновить`

Правила:

- `Назад` возвращает в предыдущий обзорный экран;
- `Домой` возвращает в центр настройки;
- `Обновить` пересобирает тот же экран на текущих данных.

### 9.7 Паттерн `Следующий рекомендуемый шаг`

На экране обязательно есть отдельный блок:

```text
Следующий шаг
/memory_rebuild
```

или

```text
Следующий шаг
Выбери источник для /reply
```

### 9.8 Паттерн `Preview + Action`

Нужен для экранов, где пользователь сначала смотрит результат, потом решает, что делать дальше.

Подходит для:

- digest preview;
- reply suggestion;
- reminders candidate;
- full-access sync result;
- memory card после rebuild;
- warning/success состояние.

Форма:

- краткий preview;
- что это значит;
- один primary action;
- 1-2 secondary actions.

### 9.9 Паттерн `danger / experimental / optional`

Danger:

- `source_disable`
- `fullaccess_logout`

Experimental:

- весь full-access section

Optional:

- provider section

В тексте карточки должен быть отдельный блок-маркер:

```text
[EXP] Experimental слой только для чтения
```

или

```text
[OPT] Этот слой не обязателен для работы core-потока
```

## 10. Tone of Voice интерфейса

Тон интерфейса:

- коротко;
- спокойно;
- по делу;
- без официоза;
- без “продающих” формулировок;
- без канцелярита;
- без кричащих предупреждений там, где достаточно честного `WARN`;
- с ритмом, удобным для мобильного Telegram.

Правила копирайта:

- одно предложение лучше трёх;
- длинные причины переносить в блок `Что это значит` или `Почему`;
- не дублировать одну и ту же мысль в сводке и в основном тексте;
- в ошибке всегда сначала смысл, потом действие;
- статус optional/experimental слоёв описывать без драматизации.

## 11. Главное меню / Setup Center

`Центр настройки` — главный экран продукта.

Он должен решать четыре задачи:

- дать общую операционную картину;
- показать следующий рекомендуемый шаг;
- дать вход во все реальные разделы;
- визуально отделить основной путь от optional и experimental веток.

### Состав центра настройки

Блоки:

- заголовок `Astra AFT / Setup`
- сводка готовности `Готово X/Y`
- next-step block
- сводка основных модулей:
  - Источники
  - Digest
  - Memory
  - Reply
  - Reminders
- сводка optional/experimental слоёв:
  - Provider
  - Full-access
- сводка ops:
  - backup/export availability
  - последний backup/export

### Inline-кнопки центра настройки

Ряд 1:

- `Статус`
- `Checklist`
- `Doctor`

Ряд 2:

- `Источники`
- `Digest`
- `Memory`

Ряд 3:

- `Reply`
- `Reminders`

Ряд 4:

- `Provider`
- `Full-access`

Ряд 5:

- `Ops`
- `Обновить`

## 12. Спецификация разделов

### 12.1 `/start`

- Цель: привязать owner chat и ввести пользователя в продукт.
- Что показать первым: короткое подтверждение, что bot-first режим готов, и путь в setup.
- Блоки карточки:
  - краткое приветствие;
  - `что это за продукт`;
  - `куда идти дальше`;
  - `быстрый self-check`.
- Inline-кнопки:
  - `Открыть Setup`
  - `Стартовый путь`
  - `Статус`
- Следующий шаг: `Открыть Setup` или `/onboarding`.
- Пустое состояние: не требуется, это сам first entry.
- Рабочее состояние: “owner chat сохранён, можно продолжать настройку”.
- Warning/error состояние:
  - если экран вызван вне личного чата, в будущей реализации стоит показать мягкий warning, что owner chat лучше фиксировать в личке;
  - при ошибке сохранять существующий безопасный fallback.

### 12.2 `/setup`

- Статус в текущем репозитории: команды нет, это планируемая навигационная оболочка.
- Цель: стать единым домашним операционным экраном для существующих команд.
- Что показать первым: готовность, следующий шаг, состояние основного пути.
- Блоки карточки:
  - сводка готовности;
  - следующий шаг;
  - основные секции;
  - optional секции;
  - ops-сводка.
- Inline-кнопки:
  - `Статус`, `Checklist`, `Doctor`
  - `Источники`, `Digest`, `Memory`
  - `Reply`, `Reminders`
  - `Provider`, `Full-access`
  - `Ops`, `Обновить`
- Следующий шаг: строится по `SystemReadinessService`.
- Пустое состояние: фактически это cold-start setup state; показывать `Готово 0/9` и вести в `/start` или `Источники`.
- Рабочее состояние: `основной путь готов`, primary CTA ведёт в один из рабочих сценариев.
- Warning/error состояние: если часть слоёв не готова, экран остаётся usable и ведёт в точку исправления, а не превращается в giant error log.

### 12.3 `/onboarding`

- Цель: коротко объяснить продукт и порядок запуска без giant wizard.
- Что показать первым: 1 абзац “что это”, затем 5 шагов запуска.
- Блоки карточки:
  - что уже есть в продукте;
  - стартовый порядок;
  - куда смотреть по пути.
- Inline-кнопки:
  - `Открыть Setup`
  - `Checklist`
  - `Doctor`
- Следующий шаг: `Источники`.
- Пустое состояние: не требуется.
- Рабочее состояние: onboarding сам по себе и есть baseline state.
- Warning/error состояние: не нужно усложнять; этот экран должен оставаться самым чистым и объясняющим.

### 12.4 `/status`

- Цель: дать короткую операционную сводку без giant log.
- Что показать первым: `Готово X/Y`, сводку по слоям, следующий шаг.
- Блоки карточки:
  - сводка готовности;
  - источники и сообщения;
  - digest;
  - memory;
  - reply;
  - reminders;
  - provider;
  - full-access;
  - ops;
  - next step.
- Inline-кнопки:
  - `Checklist`
  - `Doctor`
  - `Источники`
  - `Обновить`
  - `Домой`
- Следующий шаг: первый unresolved step из readiness.
- Пустое состояние:
  - `Готово 0/9`
  - явно видны `owner chat`, `источники`, `сообщения` как неготовые
  - primary CTA ведёт в `Источники` или `/start`.
- Рабочее состояние:
  - компактный срез состояния;
  - без длинных объяснений;
  - optional слои показываются как `[OPT]` или `[OFF]`, а не как ошибки.
- Warning/error состояние:
  - блокеры показывать в сводке и в next step;
  - провайдер недоступен показывать как некритичный warning;
  - ошибки не должны прятать core-readiness.

### 12.5 `/checklist`

- Цель: дать пошаговую setup-checklist с готово/не готово.
- Что показать первым: список пунктов в порядке запуска.
- Блоки карточки:
  - owner chat;
  - активный источник;
  - сообщения в БД;
  - digest target;
  - memory layer;
  - reply layer;
  - reminders layer;
  - provider layer;
  - full-access layer.
- Inline-кнопки:
  - `Статус`
  - `Doctor`
  - `Следующий шаг`
  - `Домой`
- Следующий шаг: первый незакрытый пункт с маркером `[WARN]`.
- Пустое состояние: список почти полностью `[WARN]`, но структура пути уже видна.
- Рабочее состояние: максимум `[OK]`, фокус на 1-2 последних недостающих слоях.
- Warning/error состояние:
  - provider/full-access не должны выглядеть как критичные красные ошибки, если основной путь уже рабочий;
  - если они выключены, это допустимое состояние.

### 12.6 `/doctor`

- Цель: дать диагностику, причины предупреждений и список исправлений.
- Что показать первым: три блока `ОК`, `Предупреждения`, `Что исправить дальше`.
- Блоки карточки:
  - ok items;
  - warnings;
  - операционный слой;
  - timestamps backup/export/full-access sync;
  - recent worker/provider/full-access errors;
  - startup warnings;
  - corrective next steps.
- Inline-кнопки:
  - `Status`
  - `Checklist`
  - `Ops`
  - `Обновить`
  - `Домой`
- Следующий шаг: первый corrective step.
- Пустое состояние: warnings всё равно могут быть даже на пустой базе; врачебный экран должен это честно объяснять.
- Рабочее состояние: warnings короткие и actionable, ok-block не должен занимать весь экран.
- Warning/error состояние:
  - это основной warning-screen системы;
  - recent errors показывать отдельно от конфигурационных предупреждений;
  - не смешивать “provider выключен” с “provider сломан”.

### 12.7 Источники

Сюда относятся:

- `/sources`
- `/source_add`
- `/source_disable`
- `/source_enable`
- passive ingest status

- Цель: управлять allowlist-источниками и дать понятную картину ingest.
- Что показать первым: сколько активных источников, сколько сообщений, есть ли данные.
- Блоки карточки:
  - сводка: активные источники, всего сообщений, источников с данными;
  - список источников;
  - статус каждого источника;
  - исключён ли он из digest или memory;
  - ingest hint.
- Inline-кнопки:
  - `Добавить`
  - `Активные`
  - `Выключенные`
  - `Digest target`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если источников нет, primary CTA = `Добавить источник`;
  - если источники есть, но данных нет, CTA = `Как подтянуть сообщения`.
- Пустое состояние:
  - “Разрешённые источники пока не настроены”;
  - краткое пояснение про `@username`, `chat_id`, форвард или reply;
  - один primary CTA `Как добавить`.
- Рабочее состояние:
  - карточка источника должна быть короткой;
  - список должен показывать status, тип, message count;
  - быстрые действия на уровне карточки: `Открыть`, `Выключить` или `Включить`.
- Warning/error состояние:
  - источник не найден;
  - Telegram не отдал данные по `@username`;
  - источник сохранён по `chat_id` вручную;
  - источник выключен;
  - источник есть, но сообщений ещё нет.

Дополнительное UX-правило:

- `source_add` должен иметь отдельную help-card с четырьмя сценариями:
  - добавить по `@username`;
  - добавить по `chat_id`;
  - переслать сообщение;
  - ответить на сообщение и вызвать команду.

### 12.8 Digest

Сюда относятся:

- `/digest_target`
- `/digest_now`
- `/digest_llm`

- Цель: собрать digest по локальным данным и показать, куда он уходит.
- Что показать первым: target, окно по умолчанию, есть ли данные для digest.
- Блоки карточки:
  - сводка: target, окно, есть ли сообщения;
  - как работает digest;
  - последние действия;
  - разница между deterministic и LLM-refine режимом.
- Inline-кнопки:
  - `Собрать 12h`
  - `Собрать 24h`
  - `Собрать 3d`
  - `Target`
  - `Provider`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если target не задан, CTA = `Настроить target`;
  - если нет сообщений, CTA = `Источники`;
  - если всё готово, CTA = `Собрать 24h`.
- Пустое состояние:
  - нет сообщений для digest;
  - target не задан;
  - объяснение, что digest читает локальную БД, а не Telegram в момент запроса.
- Рабочее состояние:
  - показывать target;
  - давать быстрый rerun по окнам;
  - после запуска digest результат отправляется отдельными сообщениями;
  - если target задан, нужно ясно сообщать, что preview показан здесь, а итог ещё и отправлен в target.
- Warning/error состояние:
  - target не задан;
  - сообщений в окне нет;
  - provider fallback при `/digest_llm`;
  - target совпадает с текущим чатом;
  - provider недоступен, но deterministic digest собран.

Digest preview-карточка:

- заголовок окна;
- 2-4 overview lines;
- key sources;
- footer с кнопками:
  - `Пересобрать 12h`
  - `Пересобрать 24h`
  - `Target`
  - `Домой`

### 12.9 Memory

Сюда относятся:

- `/memory_rebuild`
- `/chat_memory`
- `/person_memory`

- Цель: дать обзор состояния памяти и быстрый вход в карточки чатов и людей.
- Что показать первым: построена ли память, когда обновлялась, сколько карточек есть.
- Блоки карточки:
  - сводка: chat cards, person cards, last rebuild;
  - rebuild action;
  - быстрый выбор по чатам;
  - быстрый выбор по людям;
  - explanation, что memory строится только по локальной БД.
- Inline-кнопки:
  - `Пересобрать всё`
  - `Чаты`
  - `Люди`
  - `Ответы`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если памяти нет, CTA = `Пересобрать всё`;
  - если память есть, CTA = `Открыть чат с готовой memory`.
- Пустое состояние:
  - сообщений нет;
  - или память ещё не собиралась;
  - отдельный next step в зависимости от причины.
- Рабочее состояние:
  - чат-карточка показывает сводку, state, topics, loops, linked people, conflicts;
  - person-card показывает relationship, facts, sensitive topics, open loops.
- Warning/error состояние:
  - источник не найден;
  - память по чату ещё не собрана;
  - память по человеку не собрана;
  - найдено несколько совпадений по человеку, нужно уточнить `person_key`.

### 12.10 Reply

Сюда относятся:

- `/reply`
- `/reply_llm`
- `/examples_rebuild`
- `/reply_examples`
- `/style_profiles`
- `/style_set`
- `/style_unset`
- `/style_status`
- `/persona_status`

- Цель: дать одну ясную точку входа в reply-coach слой и спрятать внутреннюю сложность style/persona/few-shot под аккуратную структуру.
- Что показать первым: готов ли reply-layer, по каким чатам уже можно запрашивать suggestion.
- Блоки карточки:
  - сводка готовности;
  - быстрый выбор по reply-ready чатам;
  - few-shot status;
  - style status;
  - persona status;
  - optional LLM-refine note.
- Inline-кнопки:
  - `Выбрать чат`
  - `Примеры`
  - `Стиль`
  - `Персона`
  - `LLM-версия`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если не хватает memory, CTA = `Memory`;
  - если чат готов, CTA = `Показать reply suggestion`.
- Пустое состояние:
  - нет данных для reply;
  - мало локального контекста;
  - последнее сообщение уже исходящее;
  - memory ещё не собрана.
- Рабочее состояние:
  - reply suggestion должна быть одной чистой карточкой;
  - сверху: чат, источник, ориентир;
  - затем: effective style, persona, few-shot status;
  - затем: итоговая серия;
  - затем: почему, risk, confidence, strategy.
- Warning/error состояние:
  - `Подсказку пока не собрать`;
  - `локальных сообщений маловато`;
  - `последнее сообщение уже от тебя`;
  - `few-shot не найден` как нейтральное warning, а не ошибка;
  - `LLM-refine: fallback`.

Reply suggestion-карточка:

- заголовок `Astra AFT / Reply / <чат>`;
- preview последнего входящего сообщения;
- итоговая серия как главное тело карточки;
- техническое пояснение ниже основного результата;
- footer кнопки:
  - `Похожие ответы`
  - `Style`
  - `Назад`
  - `Домой`

### 12.11 Reminders

Сюда относятся:

- `/reminders_scan`
- `/tasks`
- `/reminders`
- callback approve/reject/postpone

- Цель: показать явный контур “найти -> подтвердить -> доставить”.
- Что показать первым: есть ли owner chat, есть ли активные reminders, есть ли кандидаты.
- Блоки карточки:
  - сводка;
  - действия сканирования;
  - active tasks;
  - active reminders;
  - заметка о доставке.
- Inline-кнопки:
  - `Скан 12h`
  - `Скан 24h`
  - `Скан 3d`
  - `Задачи`
  - `Напоминания`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если owner chat не задан, CTA = `/start`;
  - если данных нет, CTA = `Источники`;
  - если основной путь готов, CTA = `Скан 24h`.
- Пустое состояние:
  - кандидатов нет;
  - активных задач нет;
  - активных напоминаний нет.
- Рабочее состояние:
  - сводка после scan;
  - ниже отдельные candidate-cards;
  - action происходит на самой карточке кандидата.
- Warning/error состояние:
  - owner chat не задан;
  - worker path reminder_delivery не зарегистрирован;
  - сообщений для scan нет;
  - повторно обработанный кандидат;
  - некорректный callback.

Reminder candidate-card:

- заголовок `Кандидат на задачу / reminder`;
- чат;
- с кем связано;
- формулировка;
- контекст;
- срок;
- предлагаемое напоминание;
- уверенность;
- почему замечено.

Кнопки:

- `Одобрить`
- `Отменить`
- `Позже`

После callback:

- исходная карточка должна редактироваться в итоговую карточку результата действия, как это уже делает текущая логика.

### 12.12 Provider

- Реальная команда: `/provider_status`.
- Цель: показать статус optional provider layer и снять лишнюю тревожность.
- Что показать первым: `[OPT]` маркер и факт, влияет ли это сейчас на основной путь.
- Блоки карточки:
  - layer enabled/disabled;
  - provider;
  - models;
  - timeout;
  - api availability;
  - reply refine on/off;
  - digest refine on/off;
  - runtime availability;
  - reason.
- Inline-кнопки:
  - `Status`
  - `Digest`
  - `Reply`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если выключен, CTA не должен навязывать включение;
  - если включён, но не настроен, CTA = `Проверить конфиг`.
- Пустое состояние: фактически это состояние `[OFF] Provider layer выключен, deterministic fallback активен`.
- Рабочее состояние: provider configured and available.
- Warning/error состояние:
  - enabled but not configured;
  - API недоступен;
  - reply/digest refine runtime недоступен;
  - но base-product остаётся рабочим.

### 12.13 Full-access

Сюда относятся:

- `/fullaccess_status`
- `/fullaccess_login`
- `/fullaccess_logout`
- `/fullaccess_chats`
- `/fullaccess_sync`

- Цель: дать прозрачный доступ к experimental слою только для чтения без смешивания его с основным рабочим путём.
- Что показать первым: `[EXP]` маркер, `только чтение`, `только вручную`.
- Блоки карточки:
  - layer enabled/disabled;
  - api credentials;
  - phone;
  - session;
  - authorization;
  - readonly barrier;
  - sync limit;
  - synced chats/messages;
  - readiness reason.
- Inline-кнопки:
  - `Статус`
  - `Запросить код`
  - `Чаты`
  - `Sync`
  - `Logout`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если слой выключен, CTA не должен мешать основному пути;
  - если включён, но не готов, CTA = `Проверить статус`;
  - если авторизован, CTA = `Открыть список чатов`.
- Пустое состояние:
  - слой выключен;
  - или session не найдена;
  - или авторизации ещё нет.
- Рабочее состояние:
  - read-only barrier явно виден;
  - есть chat list;
  - есть manual sync.
- Warning/error состояние:
  - 2FA требуется;
  - credentials не настроены;
  - full-access не готов;
  - logout как danger action;
  - при первом sync новый чат добавляется в registry, но выключенным и исключённым из digest.

Отдельное UX-правило:

- full-access section никогда не должен выглядеть как стандартный путь запуска продукта.
- Его нужно показывать ниже core-разделов и всегда с `[EXP]`.

### 12.14 Ops / backup / export

- Реальные действия сейчас: только CLI.
- Telegram-цель раздела: сделать operational layer видимым, но не выдумывать несуществующие bot-actions.
- Что показать первым: что backup/export доступны, когда были выполнены в последний раз.
- Блоки карточки:
  - backup tool available;
  - export tool available;
  - last backup;
  - last export;
  - last full-access sync;
  - recent operational errors;
  - commands reference.
- Inline-кнопки:
  - `Doctor`
  - `Status`
  - `Домой`
  - `Обновить`
- Следующий шаг:
  - если backup ещё не делался, CTA = показать CLI-команду backup;
  - если export ещё не делался, CTA = показать CLI-команду export.
- Пустое состояние:
  - backup/export ещё не запускались;
  - командами остаются CLI-инструкции.
- Рабочее состояние:
  - показывать timestamps и пути последнего backup/export.
- Warning/error состояние:
  - backup tool недоступен не для SQLite;
  - recent worker/provider/full-access errors уже подтягиваются через operational state.

Принцип:

- пока нет bot-handlers, в этом разделе не должно быть fake-кнопок `Сделать backup` или `Сделать export`.
- это read-only operational card.

## 13. Паттерны состояний

### 13.1 Empty state

Обязательная структура:

- что отсутствует;
- почему это нормально или ожидаемо;
- что сделать дальше;
- один primary CTA.

Форма:

```text
[WARN] Данных пока нет
Почему: память ещё не строилась
Следующий шаг: /memory_rebuild
```

### 13.2 Warning state

Обязательная структура:

- что не так;
- что это ломает;
- safe next step.

Форма:

```text
[WARN] Digest target не задан
Что это значит: digest покажется только в текущем чате
Следующий шаг: /digest_target
```

### 13.3 Error state

Обязательная структура:

- короткий факт;
- без стека и внутренней кухни;
- action to recover.

Форма:

```text
[ERR] Источник не найден
Проверь chat_id или @username
```

### 13.4 Success state

Обязательная структура:

- что выполнено;
- что изменилось;
- что делать дальше.

Форма:

```text
[OK] Пересборка памяти завершена
Обновлено чатов: 3
Следующий шаг: открыть /reply
```

## 14. Какие компоненты нужно отрисовать в Figma

Минимальный обязательный набор:

1. `Setup Center`
2. `Status Card`
3. `Checklist Card`
4. `Doctor Card`
5. `Sources Management Card`
6. `Digest Preview Card`
7. `Memory Card`
8. `Reply Suggestion Card`
9. `Reminders Candidate Card`
10. `Provider Status Card`
11. `Full-access Status Card`
12. `Empty State Card`
13. `Warning State Card`
14. `Success State Card`

Что именно нужно отрисовать в каждом компоненте:

- мобильная ширина Telegram-сообщения;
- текстовая иерархия;
- markers `[OK]/[WARN]/[ERR]/[OPT]/[EXP]`;
- summary block;
- utility row `Назад / Домой / Обновить`;
- action rows;
- state variants.

Отдельно нужны screen-variants:

- cold start;
- partially ready system;
- fully ready core-path;
- provider optional off;
- full-access experimental on but not ready;
- reminders candidate pending;
- digest result with target configured;
- empty sources state.

Примечание по Figma-интеграции:

- в текущей сессии не было доступных Figma MCP resources/templates, поэтому автосоздание файла или доски не подтверждено;
- этот раздел написан как точное ТЗ для ручной сборки фреймов в Figma/FigJam.

## 15. Что потом должен внедрить Codex по этой спецификации

### 15.1 Какие renderers нужны

- `SetupCenterRenderer`
- `StatusCardRenderer`
- `ChecklistCardRenderer`
- `DoctorCardRenderer`
- `SourcesCardRenderer`
- `DigestSectionRenderer`
- `DigestPreviewFooterRenderer`
- `MemorySectionRenderer`
- `ReplySectionRenderer`
- `ReplySuggestionRenderer`
- `ReminderSectionRenderer`
- `ProviderStatusRenderer`
- `FullAccessStatusRenderer`
- `OpsStatusRenderer`
- `StateRenderer` для empty/warn/success shells

### 15.2 Какие callback routes нужны

- глобальные navigation routes из раздела 8.2;
- selection routes для выбора чата в sources/memory/reply/full-access;
- refresh routes;
- сохранение текущих `reminder:*` callbacks без изменения формата.

### 15.3 Какие inline keyboards нужны

- `setup_center_keyboard`
- `status_keyboard`
- `checklist_keyboard`
- `doctor_keyboard`
- `sources_keyboard`
- `source_item_keyboard`
- `digest_keyboard`
- `digest_result_footer_keyboard`
- `memory_keyboard`
- `memory_chat_picker_keyboard`
- `reply_keyboard`
- `reply_chat_picker_keyboard`
- `reply_result_footer_keyboard`
- `reminders_keyboard`
- `provider_keyboard`
- `fullaccess_keyboard`
- `ops_keyboard`
- `global_utility_keyboard`

### 15.4 Какие message templates нужны

- start card
- onboarding card
- setup center card
- readiness summary card
- checklist card
- doctor card
- source empty/help/list/item card
- digest section card
- digest preview/result notice
- memory overview card
- chat memory card
- person memory card
- reply overview card
- reply suggestion card
- reply examples card
- style status card
- persona status card
- reminders overview card
- reminder candidate card
- reminder action-result card
- provider status card
- full-access status card
- full-access login result
- full-access chat list
- full-access sync result
- ops status card
- empty/warn/success shells

### 15.5 Что можно переиспользовать

- `BotStatusService` для `/status`, `/checklist`, `/doctor`, `/settings`, `/sources`
- `SystemReadinessService` для next-step logic
- `OnboardingFormatter` и `HelpFormatter`
- `SourceRegistryService`
- `DigestTargetService`
- `DigestEngineService` и `DigestPublisherService`
- `MemoryService` и `MemoryFormatter`
- `ReplyEngineService`
- `ReplyExamplesFormatter`
- `StyleFormatter`
- `PersonaFormatter`
- `ReminderService` и `ReminderFormatter`
- `FullAccessFormatter`
- существующие repositories и existing counts/list methods
- `user_safe_handler` и текущую error-mapping логику

### 15.6 Что нельзя ломать в бизнес-логике

- deterministic baseline для digest и reply
- optional nature provider layer
- read-only barrier full-access
- current full-access sync semantics: chat auto-registry как `category=fullaccess`, `is_enabled=false`, `exclude_from_digest=true`
- passive ingest только по allowlist-источникам
- owner chat binding только через private chat behavior
- reminder confirm flow и callback format
- worker delivery flow
- current source-add fallback через forwarded/replied message
- текущие CLI ops-команды как source of truth для backup/export
- отсутствие auto-reply и hidden automation

### 15.7 Что можно добавить как тонкий UI-слой

- callback-навигацию;
- selection-pickers по уже известным чатам;
- alias `/setup`;
- section-overview экраны;
- unified keyboards;
- state shells;
- компактные success/warning wrappers вокруг существующих сервисных результатов.

## 16. Главные UX-проблемы текущего состояния

1. Нет единого домашнего экрана. Пользователь знает про набор команд, но не про единую карту продукта.
2. `/status`, `/checklist`, `/doctor`, `/sources`, `/help` существуют отдельно, но ещё не собираются в одну навигационную систему.
3. Команды требуют помнить синтаксис и аргументы там, где лучше дать quick-pick по уже известным чатам.
4. Reply-layer уже богатый, но интерфейсно выглядит как длинный debug output.
5. Источники, ingest и digest target живут раздельно, хотя для пользователя это один связный setup-сценарий.
6. Optional provider и experimental full-access ещё недостаточно визуально отделены от core-path.
7. Ops-слой уже есть, но из Telegram он воспринимается фрагментарно.
8. Единственный inline-flow сейчас reminders; вся остальная навигация всё ещё слишком командная.
9. Нет единого дизайн-паттерна для empty/warn/success states.
10. Нет общего паттерна `Назад / Домой / Обновить`, из-за чего интерфейс пока ощущается как набор ответов, а не как продукт.

## 17. Краткая концепция итогового UX

Astra AFT должен стать Telegram-first operational product shell:

- один home-экран;
- ясная readiness-логика;
- короткие карточки;
- кнопочная навигация;
- отдельные result-cards для действий;
- честное разделение core, optional и experimental;
- визуальная чистота вместо командного хаоса.

Если эта спецификация реализована корректно, пользователь перестаёт “вспоминать команды” и начинает “двигаться по понятной системе”, оставаясь внутри тех же реальных возможностей текущего репозитория.
