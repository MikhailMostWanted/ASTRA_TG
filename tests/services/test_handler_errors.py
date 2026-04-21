import asyncio
import importlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from services.providers.errors import ProviderUnavailableError
from storage.database import bootstrap_database, build_database_runtime


@dataclass(slots=True)
class FakeIncomingMessage:
    bot: object
    chat_id: int
    chat: object | None = None
    answers: list[str] | None = None

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=self.chat_id, type="group")
        self.answers = []

    async def answer(self, text: str):
        self.answers.append(text)
        return SimpleNamespace(message_id=1000 + len(self.answers))


class FakeBot:
    async def send_message(self, chat_id: int, text: str):
        return SimpleNamespace(chat_id=chat_id, text=text, message_id=1)


def test_status_handler_returns_safe_message_on_provider_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "handler-errors" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        management_module = importlib.import_module("bot.handlers.management")

        class ExplodingStatusService:
            async def build_status_message(self) -> str:
                raise ProviderUnavailableError("provider timeout")

        monkeypatch.setattr(
            management_module,
            "_build_status_service",
            lambda session: ExplodingStatusService(),
        )

        message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_status_command(message, runtime.session_factory)

        assert message.answers == ["Провайдер сейчас недоступен."]

        await runtime.dispose()

    asyncio.run(run_assertions())
