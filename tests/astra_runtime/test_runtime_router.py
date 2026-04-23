import asyncio

import pytest

from astra_runtime.router import RuntimeRouter
from astra_runtime.switches import RuntimeSwitches
from config.settings import Settings


def test_runtime_switches_default_to_legacy() -> None:
    switches = RuntimeSwitches.from_settings(Settings())

    assert switches.requested_backends() == {
        "chatRoster": "legacy",
        "messageWorkspace": "legacy",
        "replyGeneration": "legacy",
        "sendPath": "legacy",
        "autopilotControl": "legacy",
    }


def test_runtime_switches_validate_backend_names() -> None:
    settings = Settings(runtime_send_path_backend="experimental")

    with pytest.raises(ValueError, match="runtime_send_path_backend"):
        RuntimeSwitches.from_settings(settings)


def test_runtime_router_falls_back_to_legacy_when_new_runtime_is_not_registered() -> None:
    async def run_assertions() -> None:
        router = RuntimeRouter(
            legacy=_FakeRuntime("legacy"),
            target=None,
            switches=RuntimeSwitches(chat_roster="new"),
        )

        payload = await router.chat_roster.list_chats()
        status = router.describe()["routes"]["chatRoster"]

        assert payload == {"runtime": "legacy"}
        assert status["requested"] == "new"
        assert status["effective"] == "legacy"
        assert status["targetAvailable"] is False
        assert status["reason"] == "New runtime is not registered yet; legacy adapter remains effective."

    asyncio.run(run_assertions())


def test_runtime_router_selects_target_surface_per_switch() -> None:
    async def run_assertions() -> None:
        router = RuntimeRouter(
            legacy=_FakeRuntime("legacy"),
            target=_FakeRuntime("new"),
            switches=RuntimeSwitches(
                chat_roster="new",
                message_workspace="legacy",
            ),
        )

        roster = await router.chat_roster.list_chats()
        messages = await router.message_history.get_chat_messages(1)
        status = router.describe()["routes"]

        assert roster == {"runtime": "new"}
        assert messages == {"runtime": "legacy", "chatId": 1}
        assert status["chatRoster"]["effective"] == "new"
        assert status["messageWorkspace"]["effective"] == "legacy"

    asyncio.run(run_assertions())


class _FakeRuntime:
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def chat_roster(self):
        return self

    @property
    def message_history(self):
        return self

    @property
    def reply_workspace(self):
        return self

    @property
    def message_sender(self):
        return self

    @property
    def autopilot(self):
        return self

    async def list_chats(self, **_kwargs):
        return {"runtime": self.name}

    async def get_chat_messages(self, chat_id: int, **_kwargs):
        return {"runtime": self.name, "chatId": chat_id}
