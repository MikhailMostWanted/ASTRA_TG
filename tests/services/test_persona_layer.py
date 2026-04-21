import asyncio
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import SettingRepository, StyleProfileRepository


@dataclass(slots=True)
class FakeIncomingMessage:
    bot: object
    chat_id: int
    chat: object = field(init=False)
    answers: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(id=self.chat_id)

    async def answer(self, text: str):
        self.answers.append(text)
        return SimpleNamespace(message_id=1000 + len(self.answers))


class FakeBot:
    async def send_message(self, chat_id: int, text: str):
        return SimpleNamespace(chat_id=chat_id, text=text, message_id=1)


def test_persona_core_loads_default_owner_seed_and_formats_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "persona-core" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        persona_core_module = importlib.import_module("services.persona_core")
        persona_formatter_module = importlib.import_module("services.persona_formatter")

        async with runtime.session_factory() as session:
            service = persona_core_module.PersonaCoreService(SettingRepository(session))
            state = await service.load_state()
            report = await service.build_status_report()
            rendered = persona_formatter_module.PersonaFormatter().format_status(report)

            assert state.enabled is True
            assert state.version == "owner-core-v1"
            assert state.core is not None
            assert state.guardrails is not None
            assert state.core.opener_bank[:4] == ("ну", "а", "да", "не")
            assert state.core.active_rule_count >= 20
            assert state.guardrails.active_checks_count >= 7

            assert report.core_loaded is True
            assert report.reply_enrichment_enabled is True
            assert report.active_core_rules >= 20
            assert report.active_guardrail_checks >= 7
            assert any("длинным блоком" in rule for rule in report.anti_pattern_rules)

            assert "Persona core: загружен" in rendered
            assert "Persona enrichment для /reply: включён" in rendered
            assert "Активных core-правил:" in rendered
            assert "Активных guardrail-checks:" in rendered
            assert "Анти-паттерны:" in rendered

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_persona_adapter_and_guardrails_make_reply_more_owner_like(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "persona-adapter" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        persona_core_module = importlib.import_module("services.persona_core")
        persona_adapter_module = importlib.import_module("services.persona_adapter")
        persona_guardrails_module = importlib.import_module("services.persona_guardrails")
        style_profiles_module = importlib.import_module("services.style_profiles")

        async with runtime.session_factory() as session:
            persona_state = await persona_core_module.PersonaCoreService(
                SettingRepository(session)
            ).load_state()
            profile_model = await StyleProfileRepository(session).get_by_key("friend_explain")
            assert profile_model is not None
            profile = style_profiles_module.StyleProfileSnapshot.from_model(profile_model)

            adapter = persona_adapter_module.PersonaAdapter()
            adapted = adapter.adapt(
                messages=(
                    "Понял. В данном случае я посмотрю это сейчас и вернусь с конкретным апдейтом чуть позже.",
                ),
                profile=profile,
                persona_core=persona_state.core,
                strategy="мягко ответить",
            )

            assert adapted.applied is True
            assert len(adapted.messages) >= 2
            assert adapted.messages[0] == adapted.messages[0].lower()
            assert adapted.messages[0].startswith(("ну ", "а ", "да ", "не ", "это ", "я "))
            assert "апдейтом" not in "\n".join(adapted.messages)
            assert adapted.notes

            guardrails = persona_guardrails_module.PersonaGuardrails()
            decision = guardrails.apply(
                proposed_messages=(
                    "благодарю за сообщение!!! в данном случае предлагаю максимально корректно и обстоятельно обсудить это потому что это пиздец какой сложный момент",
                ),
                fallback_messages=("ну гляну", "вернусь позже"),
                profile=profile,
                persona_core=persona_state.core,
                guardrails=persona_state.guardrails,
            )

            assert decision.used_fallback is True
            assert decision.messages == ("ну гляну", "вернусь позже")
            assert "слишком_литературно" in decision.flags
            assert "слишком_грубо" in decision.flags
            assert "пунктуационный_шум" in decision.flags

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_persona_status_command_reports_owner_persona_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "persona-status" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        management_module = importlib.import_module("bot.handlers.management")

        fake_message = FakeIncomingMessage(bot=FakeBot(), chat_id=900)
        await management_module.handle_persona_status_command(
            fake_message,
            runtime.session_factory,
        )

        assert any("Persona core: загружен" in answer for answer in fake_message.answers)
        assert any(
            "Persona enrichment для /reply: включён" in answer
            for answer in fake_message.answers
        )
        assert any("Анти-паттерны:" in answer for answer in fake_message.answers)

        await runtime.dispose()

    asyncio.run(run_assertions())
