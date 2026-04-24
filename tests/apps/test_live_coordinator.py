from __future__ import annotations

import asyncio
from datetime import timedelta

from apps.desktop_api.live import DesktopLiveCoordinator


def test_live_coordinator_refreshes_reply_only_on_meaningful_signal() -> None:
    async def run_assertions() -> None:
        coordinator = DesktopLiveCoordinator(active_refresh_seconds=2)
        messages = [
            _message(10, "inbound", "Сможешь посмотреть это сегодня?"),
        ]
        workspace_calls = 0
        message_calls = 0

        async def fetch_workspace():
            nonlocal workspace_calls
            workspace_calls += 1
            return _workspace(messages, reply_text=f"reply-{workspace_calls}")

        async def fetch_messages():
            nonlocal message_calls
            message_calls += 1
            return _messages_payload(messages)

        initial = await coordinator.refresh_active_chat(
            chat_id=1,
            fetch_workspace=fetch_workspace,
            fetch_messages=fetch_messages,
        )
        assert initial.execute_reply_modes is True
        assert initial.payload["reply"]["suggestion"]["replyText"] == "reply-1"

        coordinator._active_states[1].last_refresh_at -= timedelta(seconds=3)  # type: ignore[operator]
        messages.append(_message(11, "inbound", "ок"))
        weak = await coordinator.refresh_active_chat(
            chat_id=1,
            fetch_workspace=fetch_workspace,
            fetch_messages=fetch_messages,
        )
        assert weak.execute_reply_modes is False
        assert weak.event["reasonCode"] == "no_new_signal"
        assert weak.event["newMessageCount"] == 1
        assert weak.event["meaningfulMessageCount"] == 0
        assert weak.payload["reply"]["suggestion"]["replyText"] == "reply-1"
        assert workspace_calls == 1
        assert message_calls == 1

        coordinator._active_states[1].last_refresh_at -= timedelta(seconds=3)  # type: ignore[operator]
        messages.append(_message(12, "inbound", "Когда сможешь прислать финальный файл?"))
        meaningful = await coordinator.refresh_active_chat(
            chat_id=1,
            fetch_workspace=fetch_workspace,
            fetch_messages=fetch_messages,
        )
        assert meaningful.execute_reply_modes is True
        assert meaningful.event["reasonCode"] == "meaningful_signal"
        assert meaningful.event["meaningfulMessageCount"] == 1
        assert meaningful.payload["reply"]["suggestion"]["replyText"] == "reply-2"
        assert workspace_calls == 2
        assert message_calls == 2

    asyncio.run(run_assertions())


def test_live_coordinator_uses_error_cooldown_and_cached_workspace() -> None:
    async def run_assertions() -> None:
        coordinator = DesktopLiveCoordinator(active_refresh_seconds=2, error_cooldown_seconds=20)
        messages = [_message(10, "inbound", "Сможешь посмотреть это сегодня?")]
        message_calls = 0

        async def fetch_workspace():
            return _workspace(messages, reply_text="cached reply")

        async def fetch_messages():
            nonlocal message_calls
            message_calls += 1
            raise RuntimeError("runtime timeout")

        await coordinator.refresh_active_chat(
            chat_id=1,
            fetch_workspace=fetch_workspace,
            fetch_messages=lambda: _messages_payload_async(messages),
        )
        coordinator._active_states[1].last_refresh_at -= timedelta(seconds=3)  # type: ignore[operator]

        degraded = await coordinator.refresh_active_chat(
            chat_id=1,
            fetch_workspace=fetch_workspace,
            fetch_messages=fetch_messages,
        )
        assert degraded.from_cache is True
        assert degraded.event["status"] == "degraded"
        assert degraded.event["reasonCode"] == "refresh_error"
        assert degraded.payload["live"]["lastError"] == "runtime timeout"

        cooldown = await coordinator.refresh_active_chat(
            chat_id=1,
            fetch_workspace=fetch_workspace,
            fetch_messages=fetch_messages,
        )
        assert cooldown.from_cache is True
        assert cooldown.event["reasonCode"] == "error_cooldown"
        assert message_calls == 1

    asyncio.run(run_assertions())


def test_live_coordinator_roster_refresh_counts_changed_items_and_dedupes_interval() -> None:
    async def run_assertions() -> None:
        coordinator = DesktopLiveCoordinator(roster_refresh_seconds=4)
        last_message_key = "telegram:-1001:10"
        calls = 0

        async def fetch_roster():
            nonlocal calls
            calls += 1
            return _roster(last_message_key)

        first = await coordinator.refresh_roster(fetch_roster=fetch_roster)
        assert first.event["changedItemCount"] == 1
        assert first.payload["live"]["reasonCode"] == "roster_poll"

        cached = await coordinator.refresh_roster(fetch_roster=fetch_roster)
        assert cached.from_cache is True
        assert cached.event["reasonCode"] == "interval_not_due"
        assert calls == 1

        filtered = await coordinator.refresh_roster(fetch_roster=fetch_roster, cache_key="reply-filter")
        assert filtered.from_cache is False
        assert calls == 2

        coordinator._roster_state.last_refresh_at -= timedelta(seconds=5)  # type: ignore[operator]
        last_message_key = "telegram:-1001:11"
        changed = await coordinator.refresh_roster(fetch_roster=fetch_roster)
        assert changed.event["changedItemCount"] == 1
        assert calls == 3

    asyncio.run(run_assertions())


async def _messages_payload_async(messages: list[dict[str, object]]) -> dict[str, object]:
    return _messages_payload(messages)


def _workspace(messages: list[dict[str, object]], *, reply_text: str) -> dict[str, object]:
    return {
        "chat": {"id": 1, "chatKey": "telegram:-1001", "runtimeChatId": -1001},
        "messages": list(messages),
        "history": {"newestMessageKey": messages[-1]["messageKey"]},
        "replyContext": {
            "available": True,
            "sourceMessageKey": messages[-1]["messageKey"],
            "focusLabel": "вопрос",
        },
        "reply": {
            "kind": "suggestion",
            "suggestion": {"replyText": reply_text},
            "actions": {"send": False},
        },
        "autopilot": None,
        "freshness": {"mode": "fresh", "syncTrigger": "runtime_poll"},
        "status": {
            "source": "new",
            "messageSource": {"newestMessageKey": messages[-1]["messageKey"]},
            "availability": {"sendAvailable": False},
        },
        "refreshedAt": "2026-04-24T10:00:00+00:00",
    }


def _messages_payload(messages: list[dict[str, object]]) -> dict[str, object]:
    return {
        "chat": {"id": 1, "chatKey": "telegram:-1001", "runtimeChatId": -1001},
        "messages": list(messages),
        "history": {"newestMessageKey": messages[-1]["messageKey"]},
        "status": {
            "source": "new",
            "syncTrigger": "runtime_poll",
            "updatedNow": True,
            "messageSource": {"newestMessageKey": messages[-1]["messageKey"]},
        },
        "refreshedAt": "2026-04-24T10:00:00+00:00",
    }


def _message(runtime_id: int, direction: str, text: str) -> dict[str, object]:
    return {
        "id": runtime_id,
        "messageKey": f"telegram:-1001:{runtime_id}",
        "runtimeMessageId": runtime_id,
        "direction": direction,
        "text": text,
        "preview": text,
        "hasMedia": False,
    }


def _roster(last_message_key: str) -> dict[str, object]:
    return {
        "items": [
            {
                "chatKey": "telegram:-1001",
                "rosterLastMessageKey": last_message_key,
            }
        ],
        "count": 1,
        "roster": {"source": "new", "degraded": False},
        "refreshedAt": "2026-04-24T10:00:00+00:00",
    }
