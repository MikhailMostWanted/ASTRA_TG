import asyncio
from dataclasses import dataclass
from pathlib import Path

from config.settings import Settings
from services.command_parser import BotCommandParser
from services.digest_target import DigestTargetService
from services.source_registry import SourceRegistryService
from services.startup import BotStartupService
from services.status_summary import BotStatusService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, SettingRepository, SystemRepository


@dataclass(slots=True)
class FakeChat:
    id: int
    type: str
    title: str | None = None
    username: str | None = None


@dataclass(slots=True)
class FakeForwardOriginChannel:
    chat: FakeChat


@dataclass(slots=True)
class FakeMessage:
    forward_origin: object | None = None
    forward_from_chat: object | None = None
    reply_to_message: object | None = None
    sender_chat: object | None = None


@dataclass(slots=True)
class FakeResolvedChat:
    telegram_chat_id: int
    title: str
    handle: str | None
    chat_type: str


@dataclass(slots=True)
class FakeChatResolver:
    resolved: dict[str, FakeResolvedChat]

    async def resolve_chat(self, reference: str) -> FakeResolvedChat | None:
        return self.resolved.get(reference)


def test_command_parser_supports_args_and_forwarded_sources() -> None:
    parser = BotCommandParser()

    parsed_username = parser.parse_source_add_arguments("@mychannel")
    assert parsed_username.reference == "@mychannel"
    assert parsed_username.chat_type is None
    assert parsed_username.title is None

    parsed_numeric = parser.parse_source_add_arguments("123456789 группа Новости дня")
    assert parsed_numeric.reference == "123456789"
    assert parsed_numeric.chat_type == "group"
    assert parsed_numeric.title == "Новости дня"

    extracted = parser.extract_source_candidate(
        FakeMessage(
            forward_origin=FakeForwardOriginChannel(
                chat=FakeChat(
                    id=-100500,
                    type="channel",
                    title="Канал теста",
                    username="test_channel",
                )
            )
        )
    )
    assert extracted is not None
    assert extracted.telegram_chat_id == -100500
    assert extracted.title == "Канал теста"
    assert extracted.handle == "test_channel"
    assert extracted.chat_type == "channel"


def test_services_manage_sources_digest_target_and_status(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "management" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        parser = BotCommandParser()
        resolver = FakeChatResolver(
            resolved={
                "@news": FakeResolvedChat(
                    telegram_chat_id=-100200,
                    title="Новости дня",
                    handle="news",
                    chat_type="channel",
                ),
                "@digest": FakeResolvedChat(
                    telegram_chat_id=-100900,
                    title="Digest канал",
                    handle="digest",
                    chat_type="channel",
                ),
            }
        )

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            repo_settings = SettingRepository(session)
            system = SystemRepository(session)

            source_service = SourceRegistryService(chats, resolver=resolver)
            digest_target_service = DigestTargetService(repo_settings, resolver=resolver)
            status_service = BotStatusService(chats, repo_settings, system)

            add_result = await source_service.register_source(
                parser.parse_source_add_arguments("@news")
            )
            assert add_result.chat.telegram_chat_id == -100200
            assert add_result.chat.title == "Новости дня"
            assert add_result.action == "created"
            await session.commit()

            fallback_source = parser.extract_source_candidate(
                FakeMessage(
                    forward_origin=FakeForwardOriginChannel(
                        chat=FakeChat(
                            id=-100201,
                            type="group",
                            title="Форвард-группа",
                            username=None,
                        )
                    )
                )
            )
            forwarded_result = await source_service.register_source(
                parser.parse_source_add_arguments(None),
                fallback_source=fallback_source,
            )
            assert forwarded_result.chat.telegram_chat_id == -100201
            assert forwarded_result.action == "created"
            await session.commit()

            disabled_result = await source_service.set_source_enabled("@news", is_enabled=False)
            assert disabled_result is not None
            assert disabled_result.chat.is_enabled is False

            target = await digest_target_service.set_target(
                parser.parse_digest_target_arguments("@digest")
            )
            await session.commit()

            assert target.chat_id == -100900
            assert target.label == "@digest"

            status_text = await status_service.build_status_message()
            settings_text = await status_service.build_settings_message()
            sources_messages = await status_service.build_sources_messages()

            assert "Всего источников: 2" in status_text
            assert "Активных источников: 1" in status_text
            assert "Схема БД: 20260420_01" in status_text
            assert "digest_target_chat_id: -100900" in settings_text
            assert "digest_target_label: @digest" in settings_text
            assert any("Новости дня" in message for message in sources_messages)
            assert any("Форвард-группа" in message for message in sources_messages)

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_start_message_explains_onboarding() -> None:
    message = BotStartupService().build_start_message()

    assert "Astra AFT" in message
    assert "digest" in message.lower()
    assert "добавить источники" in message.lower()
    assert "канал доставки" in message.lower()
