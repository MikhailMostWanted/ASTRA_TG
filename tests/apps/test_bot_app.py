import asyncio

from apps.bot.app import build_bot_runtime, configure_bot_commands
from config.settings import Settings


class FakeBot:
    def __init__(self) -> None:
        self.commands = None

    async def set_my_commands(self, commands) -> None:
        self.commands = commands


def test_build_bot_runtime_requires_telegram_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    settings = Settings()

    try:
        build_bot_runtime(settings)
    except RuntimeError as error:
        assert "TELEGRAM_BOT_TOKEN" in str(error)
    else:
        raise AssertionError("build_bot_runtime should require TELEGRAM_BOT_TOKEN")


def test_build_bot_runtime_creates_dispatcher(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

    settings = Settings()
    runtime = build_bot_runtime(settings)

    assert runtime.dispatcher is not None
    assert runtime.settings.telegram_bot_token == "123456:TEST_TOKEN"


def test_configure_bot_commands_registers_management_commands() -> None:
    fake_bot = FakeBot()

    asyncio.run(configure_bot_commands(fake_bot))

    assert fake_bot.commands is not None
    assert [command.command for command in fake_bot.commands] == [
        "start",
        "help",
        "status",
        "sources",
        "source_add",
        "source_disable",
        "source_enable",
        "digest_target",
        "settings",
    ]
