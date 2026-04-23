# Runtime migration plan

## Цель pivot

Astra остаётся оболочкой продукта: desktop, bot, CLI, operational UX, storage, memory, digest, reminders и настройки остаются в этом репозитории. Меняется внутренний контур Telegram/reply/send/autopilot, который сейчас вырос из MVP-слоёв и должен быть заменён по частям без остановки рабочего запуска.

Целевая схема:

- Astra shell: `apps/desktop`, `apps/desktop_api`, `apps/bot`, `apps/cli`, `apps/worker`, `storage`, `services` для продуктовых функций.
- New Telegram runtime: отдельная реализация контрактов `astra_runtime.contracts.TelegramRuntime`.
- New reply/send/autopilot contour: replaceable `DraftReplyWorkspace`, `MessageSender`, `AutopilotControlSurface`.
- Desktop и bot: интерфейсы управления, которые не должны знать детали Telethon или будущего runtime.
- Legacy layer: текущий `fullaccess`, старый reply engine, старый autopilot service и legacy-ветки `DesktopBridge`.

## Что остаётся от Astra

- Product shell: desktop UI, desktop API routes, bot commands, CLI process manager.
- Local source of truth: SQLite schema, repositories, `messages`, `chats`, memory, digest, reminders, settings.
- Existing deterministic value: digest, memory, reminders, setup/onboarding, provider fallback rules.
- Observability and operations: status, doctor, logs, startup validation, backup/export.

## Что считается legacy

- `fullaccess/*`: текущий Telethon full-access transport, auth, chat discovery, sync и send.
- `services/reply_engine.py` плюс текущие helper-сервисы reply strategy/classifier/context/style/persona в роли старого reply-core.
- `services/autopilot.py`: текущая state machine, pending draft и send decision поверх старого reply/send.
- Legacy branches in `apps/desktop_api/bridge.py`: `_legacy_list_chats`, `_legacy_get_chat_workspace`, `_legacy_get_chat_messages`, `_legacy_get_reply_preview`, `_legacy_send_chat_message`, `_legacy_update_*autopilot`.
- Bot management factories in `bot/handlers/management.py`, которые напрямую собирают old fullaccess/reply services.

Legacy-код сейчас не удаляется. Он сохранён как рабочий fallback за `astra_runtime.legacy.LegacyAstraRuntime`.

## Новый целевой контур

Контракты заведены в `astra_runtime/contracts.py`:

- `TelegramRuntime` - aggregate runtime for all replaceable Telegram surfaces.
- `ChatRoster` - список чатов для desktop/bot control surfaces.
- `MessageHistory` - чтение сообщений и active chat workspace/tail refresh.
- `DraftReplyWorkspace` - reply result и preview payload.
- `MessageSender` - outbound send path.
- `AutopilotControlSurface` - настройки и будущие действия autopilot.

`astra_runtime/router.py` выбирает legacy или new runtime по surface, а `astra_runtime/switches.py` читает switches из `Settings`.

## Feature switches

По умолчанию всё остаётся на `legacy`. Для будущего поэтапного переключения добавлены настройки:

- `RUNTIME_CHAT_ROSTER_BACKEND=legacy|new`
- `RUNTIME_MESSAGE_WORKSPACE_BACKEND=legacy|new`
- `RUNTIME_REPLY_GENERATION_BACKEND=legacy|new`
- `RUNTIME_SEND_PATH_BACKEND=legacy|new`
- `RUNTIME_AUTOPILOT_CONTROL_BACKEND=legacy|new`

Если requested backend равен `new`, но target runtime ещё не зарегистрирован, effective backend остаётся `legacy`. Это намеренно: переключатели можно включать в конфиге заранее без падения запуска. Когда новый runtime будет передан в `DesktopBridge` или `create_app(..., target_runtime=...)`, `RuntimeRouter` начнёт отдавать selected surface из нового runtime.

## Порядок безопасной миграции

1. Chat roster: реализовать новый `ChatRoster`, подключить только `RUNTIME_CHAT_ROSTER_BACKEND=new`, сравнить payload desktop списка с legacy.
2. Message history/workspace: реализовать `MessageHistory`, сначала read-only messages, потом active tail refresh. Проверить freshness payload и отсутствие регрессий в workspace.
3. Reply generation: реализовать `DraftReplyWorkspace`, включить только `RUNTIME_REPLY_GENERATION_BACKEND=new`. Проверить `/reply-preview` и embedded reply в desktop workspace.
4. Send path: реализовать `MessageSender`, включить `RUNTIME_SEND_PATH_BACKEND=new` сначала только для manual send. Проверить запись outbound сообщения в локальный store и journal.
5. Autopilot control: реализовать `AutopilotControlSurface` поверх нового reply/send контура. Только после этого включать `RUNTIME_AUTOPILOT_CONTROL_BACKEND=new`.
6. Bot migration: после desktop стабилизации перевести bot commands off direct legacy factories onto the same runtime contracts.

## Критерии удаления legacy

Legacy можно удалять только после выполнения всех условий:

- Все switches стабильно работают на `new` в desktop API и bot control surfaces.
- Tests cover new runtime routes: roster, messages/workspace, reply preview, manual send, autopilot settings/decision.
- Operational dashboard/doctor не ссылаются на fullaccess как основной путь.
- `source_adapter=fullaccess` либо больше не пишется, либо явно поддерживается migration/backfill code.
- Есть fallback или documented rollback на уровне config до удаления.
- Минимум один полный ручной сценарий пройден: открыть desktop, выбрать чат, обновить workspace, получить reply, отправить вручную, увидеть journal.

План удаления:

- Удалить `fullaccess/client.py`, `fullaccess/sync.py`, `fullaccess/send.py`, `fullaccess/auth.py`, `fullaccess/formatter.py`, `fullaccess/cli.py` после замены auth/sync/send/status.
- Удалить `LegacyAstraRuntime` и `_legacy_*` branches в `DesktopBridge` после удаления всех legacy switches.
- Удалить direct legacy factories in `bot/handlers/management.py` после перевода bot на runtime contracts.
- Удалить старый `services/autopilot.py` после переноса pending draft, cooldown, journal и send decisions в new autopilot contour.
- Сократить старый reply engine только после того, как новый `DraftReplyWorkspace` покрывает deterministic fallback, provider fallback, style/persona/few-shot observability.
