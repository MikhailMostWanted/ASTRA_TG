from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from aiogram import Bot

from astra_runtime.contracts import TelegramRuntime
from astra_runtime.legacy import LegacyAstraRuntime
from astra_runtime.manager import LegacyRuntimeBackend, RuntimeManager, StaticRuntimeBackend
from astra_runtime.new_telegram import (
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramRuntimeConfig,
    NewTelegramRuntimeService,
)
from astra_runtime.switches import RuntimeSwitches
from apps.cli.processes import inspect_process, start_component, stop_component
from apps.cli.runtime import (
    COMPONENTS,
    check_database,
    check_provider,
    get_repository_root,
    tail_log,
)
from config.settings import Settings
from fullaccess.auth import FullAccessAuthService
from fullaccess.copy import LOCAL_LOGIN_COMMAND, local_login_instruction_lines
from fullaccess.send import FullAccessSendService
from fullaccess.sync import FullAccessSyncService
from services.autopilot import AutopilotService
from services.chat_memory_builder import ChatMemoryBuilder
from services.command_parser import ParsedDigestTargetCommand, ParsedSourceAddCommand
from services.digest_builder import DigestBuilder
from services.digest_engine import DigestEngineService
from services.digest_formatter import DigestFormatter
from services.digest_target import DigestTargetService
from services.memory_builder import MemoryService
from services.memory_formatter import MemoryFormatter
from services.operational_state import OperationalStateService
from services.operational_tools import OperationalBackupService, OperationalExportService
from services.people_memory_builder import PeopleMemoryBuilder
from services.persona_adapter import PersonaAdapter
from services.persona_core import PersonaCoreService
from services.persona_guardrails import PersonaGuardrails
from services.providers.digest_refiner import DigestLLMRefiner
from services.providers.manager import ProviderManager
from services.providers.reply_refiner import ReplyLLMRefiner
from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter
from services.reminder_service import ReminderService
from services.reply_classifier import ReplyClassifier
from services.reply_context_builder import ReplyContextBuilder
from services.reply_engine import ReplyEngineService
from services.reply_examples_retriever import ReplyExamplesRetriever
from services.reply_strategy import ReplyStrategyResolver
from services.source_registry import SourceRegistryService
from services.status_summary import BotStatusService
from services.style_adapter import StyleAdapter
from services.style_selector import StyleSelectorService
from services.system_health import SystemHealthService
from services.system_readiness import OperationalFacts, OperationalReport, SystemReadinessService
from services.telegram_lookup import TelegramChatResolver
from services.workflow_journal import WorkflowJournalService
from models import Message
from storage.database import DatabaseRuntime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    ChatStyleOverrideRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReminderRepository,
    ReplyExampleRepository,
    SettingRepository,
    StyleProfileRepository,
    SystemRepository,
    TaskRepository,
)

from .serializers import (
    build_chat_reference,
    serialize_chat,
    serialize_datetime,
    serialize_digest,
    serialize_fullaccess_chat,
    serialize_fullaccess_status,
    serialize_fullaccess_sync_result,
    serialize_message,
    serialize_process_state,
    serialize_reminder,
    serialize_reply_result,
    serialize_task,
)


DEFAULT_DIGEST_WINDOW = "24h"
DEFAULT_LOG_TAIL = 80
AUTO_WORKSPACE_SYNC_MIN_SECONDS = 12


@dataclass(frozen=True, slots=True)
class ChatTailRefreshStatus:
    attempted: bool
    updated: bool
    error: str | None = None
    trigger: str | None = None


@dataclass(slots=True)
class DesktopBridge:
    """Desktop control shell with explicit routing to legacy or target runtime.

    The public methods below are routing points. The `_legacy_*` methods keep
    the old contour alive until the new runtime implements the same contracts.
    """

    settings: Settings
    runtime: DatabaseRuntime
    target_runtime: TelegramRuntime | None = None
    runtime_switches: RuntimeSwitches | None = None
    _runtime_manager: RuntimeManager = field(init=False, repr=False)
    _new_runtime_service: NewTelegramRuntimeService | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self._runtime_manager = RuntimeManager(
            switches=self.runtime_switches or RuntimeSwitches.from_settings(self.settings),
        )
        self._runtime_manager.register_backend(
            LegacyRuntimeBackend(LegacyAstraRuntime(self))
        )
        if self.target_runtime is not None:
            self._runtime_manager.register_backend(
                StaticRuntimeBackend(
                    backend="new",
                    runtime=self.target_runtime,
                    name="external-target-runtime",
                    route_available=True,
                )
            )
            return

        self._new_runtime_service = NewTelegramRuntimeService(
            config=NewTelegramRuntimeConfig.from_settings(self.settings),
            auth_store=DatabaseNewTelegramAuthSessionStore(self.runtime.session_factory),
            session_factory=self.runtime.session_factory,
        )
        self._runtime_manager.register_backend(self._new_runtime_service)

    async def startup_runtime_layer(self) -> None:
        await self._runtime_manager.bootstrap()

    async def shutdown_runtime_layer(self) -> None:
        await self._runtime_manager.shutdown()

    def describe_runtime(self) -> dict[str, object]:
        return self._runtime_manager.describe_routes()

    async def get_runtime_status(self) -> dict[str, Any]:
        status = await self._runtime_manager.status()
        status["managedProcess"] = serialize_process_state(inspect_process("new-runtime"))
        return status

    async def get_new_runtime_health(self) -> dict[str, Any]:
        return await self._runtime_manager.health("new")

    async def get_dashboard(self) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            report = await self._build_operational_report(session)
            facts = report.facts
            last_digest = await DigestRepository(session).get_last_digest()

        process_states = [inspect_process(component) for component in COMPONENTS]
        database = await check_database(self.settings)
        provider_api = await check_provider(self.settings)
        runtime_status = await self.get_runtime_status()

        return {
            "repositoryRoot": str(get_repository_root()),
            "database": {
                "available": database.available,
                "detail": database.detail,
                "databaseUrl": database.database_url,
                "sqlitePath": str(database.sqlite_path) if database.sqlite_path is not None else None,
            },
            "providerApi": {
                "enabled": provider_api.enabled,
                "configured": provider_api.configured,
                "available": provider_api.available,
                "providerName": provider_api.provider_name,
                "reason": provider_api.reason,
            },
            "summary": {
                "readyChecks": report.ready_check_count,
                "totalChecks": report.total_check_count,
                "nextSteps": list(report.next_steps),
                "warnings": list(report.warnings),
            },
            "statusCards": self._build_status_cards(
                facts=facts,
                process_states=process_states,
                database=database,
                runtime_status=runtime_status,
            ),
            "attention": self._build_attention_items(report),
            "activity": self._build_activity_items(facts, last_digest),
            "errors": self._build_error_items(facts, database.available, provider_api.available),
            "astraNow": self._build_now_items(facts, process_states),
            "quickActions": [
                {"id": "start", "label": "Запустить", "kind": "primary", "enabled": True},
                {"id": "stop", "label": "Остановить", "kind": "secondary", "enabled": True},
                {"id": "restart", "label": "Перезапустить", "kind": "secondary", "enabled": True},
                {"id": "refresh", "label": "Обновить", "kind": "ghost", "enabled": True},
                {"id": "sync", "label": "Синхронизировать", "kind": "secondary", "enabled": True},
                {"id": "memory", "label": "Пересобрать память", "kind": "secondary", "enabled": True},
                {"id": "digest", "label": "Запустить дайджест", "kind": "secondary", "enabled": True},
            ],
            "processes": [serialize_process_state(state) for state in process_states],
            "runtime": runtime_status,
        }

    async def get_ops_overview(self, *, tail: int = DEFAULT_LOG_TAIL) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            report = await self._build_operational_report(session)

        doctor = SystemHealthService().build_report(report)
        process_states = [inspect_process(component) for component in COMPONENTS]
        return {
            "doctor": {
                "okItems": list(doctor.ok_items),
                "warnings": list(doctor.warnings),
                "nextSteps": list(doctor.next_steps),
            },
            "processes": [
                {
                    **serialize_process_state(state),
                    "lines": tail_log(state.log_path, lines=tail),
                }
                for state in process_states
            ],
            "actions": [
                {"id": "backup", "label": "Backup", "enabled": True},
                {"id": "export", "label": "Export", "enabled": True},
                {"id": "doctor", "label": "Doctor", "enabled": True},
                {"id": "status", "label": "Status", "enabled": True},
            ],
            "runtime": await self.get_runtime_status(),
        }

    async def list_chats(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
    ) -> dict[str, Any]:
        return await self._runtime_manager.surface("chatRoster").list_chats(
            search=search,
            filter_key=filter_key,
            sort_key=sort_key,
        )

    async def _legacy_list_chats(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: pre-pivot roster comes from local DB projections.
        # New chat discovery and roster semantics should implement ChatRoster.
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            message_repository = MessageRepository(session)
            chat_memory_repository = ChatMemoryRepository(session)
            setting_repository = SettingRepository(session)

            chats = await chat_repository.list_chats()
            counts = await message_repository.count_messages_by_chat()
            last_messages = await message_repository.get_last_messages_by_chat(
                chat_ids=[chat.id for chat in chats]
            )
            memory_map = {
                item.chat_id: item
                for item in await chat_memory_repository.list_chat_memory(limit=max(100, len(chats) or 1))
            }
            digest_target = await DigestTargetService(setting_repository).get_target()

            items: list[dict[str, Any]] = []
            for chat in chats:
                last_message = last_messages.get(chat.id)
                items.append(
                    serialize_chat(
                        chat,
                        message_count=counts.get(chat.id, 0),
                        last_message=last_message,
                        memory=memory_map.get(chat.id),
                        is_digest_target=digest_target.chat_id == chat.telegram_chat_id,
                        session_file=self.settings.fullaccess_session_file,
                    )
                )

        normalized_query = (search or "").strip().casefold()
        if normalized_query:
            items = [
                item
                for item in items
                if normalized_query in item["title"].casefold()
                or normalized_query in (item["handle"] or "").casefold()
                or normalized_query in str(item["telegramChatId"])
            ]

        if filter_key == "enabled":
            items = [item for item in items if item["enabled"]]
        elif filter_key == "reply":
            items = [item for item in items if item["type"] != "channel" and item["messageCount"] >= 3]
        elif filter_key == "fullaccess":
            items = [item for item in items if item["syncStatus"] == "fullaccess"]

        if sort_key == "title":
            items.sort(key=lambda item: ((not item["enabled"]), item["title"].casefold(), item["telegramChatId"]))
        elif sort_key == "messages":
            items.sort(
                key=lambda item: (-item["messageCount"], item["title"].casefold(), item["telegramChatId"])
            )
        else:
            items.sort(
                key=lambda item: (
                    item["lastMessageAt"] is None,
                    item["lastMessageAt"] or "",
                    item["title"].casefold(),
                ),
                reverse=True,
            )

        return {
            "items": items,
            "count": len(items),
            "filters": {"active": filter_key, "sort": sort_key, "search": search or ""},
            "refreshedAt": serialize_datetime(datetime.now(timezone.utc)),
        }

    async def get_chat_workspace(self, chat_id: int, *, limit: int = 80) -> dict[str, Any]:
        return await self._runtime_manager.surface("messageWorkspace").get_chat_workspace(
            chat_id,
            limit=limit,
        )

    async def _legacy_get_chat_workspace(self, chat_id: int, *, limit: int = 80) -> dict[str, Any]:
        # LEGACY_RUNTIME: workspace refresh still uses fullaccess tail sync.
        # Future message workspace implementations should live behind MessageHistory.
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Чат не найден.")

            tail_refresh = await self._maybe_refresh_chat_tail(session, chat=chat)
            if tail_refresh.error:
                chat = await chat_repository.get_by_id(chat_id)
                if chat is None:
                    raise LookupError("Чат не найден.")
            return await self._build_workspace_payload(
                session,
                chat=chat,
                limit=limit,
                tail_refresh=tail_refresh,
            )

    async def get_chat_messages(self, chat_id: int, *, limit: int = 80) -> dict[str, Any]:
        return await self._runtime_manager.surface("messageWorkspace").get_chat_messages(
            chat_id,
            limit=limit,
        )

    async def _legacy_get_chat_messages(self, chat_id: int, *, limit: int = 80) -> dict[str, Any]:
        # LEGACY_RUNTIME: direct local message-store read.
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            message_repository = MessageRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Чат не найден.")

            recent_desc = await message_repository.get_recent_messages(chat_id=chat.id, limit=max(1, limit))
            messages = list(reversed(recent_desc))
            return {
                "chat": serialize_chat(
                    chat,
                    message_count=await message_repository.count_messages_for_chat(chat_id=chat.id),
                    last_message=recent_desc[0] if recent_desc else None,
                    session_file=self.settings.fullaccess_session_file,
                ),
                "messages": [
                    serialize_message(
                        message,
                        session_file=self.settings.fullaccess_session_file,
                        telegram_chat_id=chat.telegram_chat_id,
                    )
                    for message in messages
                ],
                "refreshedAt": serialize_datetime(datetime.now(timezone.utc)),
            }

    async def get_reply_preview(
        self,
        chat_id: int,
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        return await self._runtime_manager.surface("replyGeneration").get_reply_preview(
            chat_id,
            use_provider_refinement=use_provider_refinement,
        )

    async def _legacy_get_reply_preview(
        self,
        chat_id: int,
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: old deterministic/provider reply engine.
        # New reply generation must replace DraftReplyWorkspace instead.
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Чат не найден.")

            result = await self._legacy_build_reply_result(
                session,
                build_chat_reference(chat),
                use_provider_refinement=use_provider_refinement,
            )
            fullaccess_status = await self._build_fullaccess_auth_service(session).build_status_report()
            return self._decorate_reply_payload(
                serialize_reply_result(result),
                write_ready=fullaccess_status.ready_for_manual_send,
            )

    async def send_chat_message(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        reply_to_source_message_id: int | None = None,
    ) -> dict[str, Any]:
        return await self._runtime_manager.surface("sendPath").send_chat_message(
            chat_id,
            text=text,
            source_message_id=source_message_id,
            reply_to_source_message_id=reply_to_source_message_id,
        )

    async def _legacy_send_chat_message(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        reply_to_source_message_id: int | None = None,
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: writes still go through fullaccess.send.
        # New send-path should implement MessageSender and keep this method untouched.
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            message_repository = MessageRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Чат не найден.")

            send_result = await self._build_fullaccess_send_service(session).send_chat_message(
                chat,
                text=text,
                reply_to_source_message_id=reply_to_source_message_id or source_message_id,
                trigger="desktop_manual",
            )
            await self._build_autopilot_service(session).record_manual_send(
                chat_id=chat.id,
                source_message_id=source_message_id,
                sent_message_id=send_result.sent_message_id,
                text=text,
                actor="desktop",
            )
            await session.commit()

            updated_chat = await chat_repository.get_by_id(chat_id)
            if updated_chat is None:
                raise LookupError("Чат не найден.")
            sent_message = await message_repository.get_by_id(send_result.sent_message_id)
            workspace = await self._build_workspace_payload(
                session,
                chat=updated_chat,
                limit=80,
                tail_refresh=ChatTailRefreshStatus(attempted=False, updated=False, trigger="manual_send"),
            )
            return {
                "ok": True,
                "sentMessage": (
                    serialize_message(
                        sent_message,
                        session_file=self.settings.fullaccess_session_file,
                        telegram_chat_id=updated_chat.telegram_chat_id,
                    )
                    if sent_message is not None
                    else None
                ),
                "workspace": workspace,
            }

    async def update_autopilot_global(
        self,
        *,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
    ) -> dict[str, Any]:
        return await self._runtime_manager.surface("autopilotControl").update_autopilot_global(
            master_enabled=master_enabled,
            allow_channels=allow_channels,
        )

    async def _legacy_update_autopilot_global(
        self,
        *,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: settings-only autopilot control surface.
        async with self.runtime.session_factory() as session:
            payload = await self._build_autopilot_service(session).update_global_settings(
                master_enabled=master_enabled,
                allow_channels=allow_channels,
            )
            await session.commit()
            return {"settings": payload}

    async def update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        return await self._runtime_manager.surface("autopilotControl").update_chat_autopilot(
            chat_id,
            trusted=trusted,
            mode=mode,
        )

    async def _legacy_update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: chat flags and draft overview are still old service state.
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            message_repository = MessageRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Чат не найден.")
            updated_chat = await self._build_autopilot_service(session).update_chat_settings(
                chat,
                trusted=trusted,
                mode=mode,
            )
            await session.commit()
            fullaccess_status = await self._build_fullaccess_auth_service(session).build_status_report()
            reply_result = await self._runtime_manager.surface("replyGeneration").build_reply_result(
                build_chat_reference(updated_chat)
            )
            overview = await self._build_autopilot_service(session).build_chat_overview(
                chat=updated_chat,
                reply_result=reply_result,
                write_ready=fullaccess_status.ready_for_manual_send,
            )
            return {
                "chat": serialize_chat(
                    updated_chat,
                    message_count=await message_repository.count_messages_for_chat(chat_id=updated_chat.id),
                    last_message=await _load_last_message(message_repository, updated_chat.id),
                    session_file=self.settings.fullaccess_session_file,
                ),
                "autopilot": overview,
            }

    async def list_sources(self) -> dict[str, Any]:
        chats = await self.list_chats(sort_key="title")
        return {
            "items": chats["items"],
            "count": chats["count"],
            "onboarding": (
                "Источники управляют тем, откуда Astra берёт локальные сообщения для анализа, памяти и reply."
            ),
        }

    async def add_source(
        self,
        *,
        reference: str | None,
        title: str | None,
        chat_type: str | None,
    ) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            async with self._telegram_resolver() as resolver:
                result = await SourceRegistryService(
                    repository=chat_repository,
                    resolver=resolver,
                ).register_source(
                    ParsedSourceAddCommand(
                        reference=reference,
                        chat_type=chat_type,
                        title=title,
                    )
                )
            await session.commit()
            return {
                "message": result.to_user_message(),
                "source": serialize_chat(
                    result.chat,
                    message_count=await MessageRepository(session).count_messages_for_chat(chat_id=result.chat.id),
                    last_message=await _load_last_message(MessageRepository(session), result.chat.id),
                    session_file=self.settings.fullaccess_session_file,
                ),
            }

    async def set_source_enabled(self, chat_id: int, *, is_enabled: bool) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Источник не найден.")

            result = await SourceRegistryService(repository=chat_repository).set_source_enabled(
                str(chat.telegram_chat_id),
                is_enabled=is_enabled,
            )
            if result is None:
                raise LookupError("Источник не найден.")
            await session.commit()
            updated_chat = await chat_repository.get_by_id(chat_id)
            assert updated_chat is not None
            return {
                "message": result.to_user_message(),
                "source": serialize_chat(
                    updated_chat,
                    message_count=await MessageRepository(session).count_messages_for_chat(chat_id=chat_id),
                    last_message=await _load_last_message(MessageRepository(session), chat_id),
                    session_file=self.settings.fullaccess_session_file,
                ),
            }

    async def sync_source(self, chat_id: int) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            chat = await chat_repository.get_by_id(chat_id)
            if chat is None:
                raise LookupError("Источник не найден.")

            result = await self._build_fullaccess_sync_service(session).sync_chat(build_chat_reference(chat))
            await session.commit()
            return serialize_fullaccess_sync_result(
                result,
                session_file=self.settings.fullaccess_session_file,
            )

    async def get_fullaccess_overview(self) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            report = await self._build_fullaccess_auth_service(session).build_status_report()
            return {
                "status": serialize_fullaccess_status(report),
                "instructions": list(local_login_instruction_lines()),
                "localLoginCommand": LOCAL_LOGIN_COMMAND,
                "onboarding": (
                    "Full-access работает только локально: чтение включено всегда после входа, "
                    "ручная отправка доступна только при FULLACCESS_READONLY=false. "
                    "Код входа нельзя отправлять в Telegram-бота."
                ),
            }

    async def request_fullaccess_code(self) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            result = await self._build_fullaccess_auth_service(session).begin_login()
            await session.commit()
            return {
                "kind": result.kind,
                "phone": result.phone,
                "instructions": list(result.instructions),
            }

    async def complete_fullaccess_login(
        self,
        *,
        code: str,
        password: str | None = None,
    ) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            service = self._build_fullaccess_auth_service(session)
            result = await service.complete_login(
                code,
                password_callback=(lambda: password or "") if password is not None else None,
            )
            await session.commit()
            return {
                "kind": result.kind,
                "phone": result.phone,
                "instructions": list(result.instructions),
            }

    async def logout_fullaccess(self) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            result = await self._build_fullaccess_auth_service(session).logout()
            await session.commit()
            return {
                "sessionRemoved": result.session_removed,
                "pendingAuthCleared": result.pending_auth_cleared,
            }

    async def list_fullaccess_chats(self, *, limit: int = 25) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            result = await self._build_fullaccess_sync_service(session).list_chats(limit=limit)
            return {
                "items": [
                    serialize_fullaccess_chat(
                        chat,
                        session_file=self.settings.fullaccess_session_file,
                    )
                    for chat in result.chats
                ],
                "truncated": result.truncated,
                "returnedCount": result.returned_count,
            }

    async def sync_fullaccess_chat(self, *, reference: str) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            result = await self._build_fullaccess_sync_service(session).sync_chat(reference)
            await session.commit()
            return serialize_fullaccess_sync_result(
                result,
                session_file=self.settings.fullaccess_session_file,
            )

    async def get_memory_overview(self, *, limit: int = 20) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            setting_repository = SettingRepository(session)
            chat_memory_repository = ChatMemoryRepository(session)
            person_memory_repository = PersonMemoryRepository(session)

            chat_items = await chat_memory_repository.list_chat_memory(limit=limit)
            stats = await setting_repository.get_value("memory.last_rebuild_stats")
            return {
                "summary": {
                    "chatCards": await chat_memory_repository.count_chat_memory(),
                    "peopleCards": await person_memory_repository.count_people_memory(),
                    "lastRebuildAt": serialize_datetime(
                        await setting_repository.get_value("memory.last_rebuild_at")
                        or await chat_memory_repository.get_last_updated_at()
                    ),
                    "lastRebuildStats": stats if isinstance(stats, dict) else None,
                },
                "items": [
                    {
                        "id": item.id,
                        "chatId": item.chat_id,
                        "chatTitle": item.chat.title if item.chat is not None else None,
                        "summaryShort": item.chat_summary_short,
                        "summaryLong": item.chat_summary_long,
                        "currentState": item.current_state,
                        "topics": list(item.dominant_topics_json or []),
                        "recentConflicts": list(item.recent_conflicts_json or []),
                        "pendingTasks": list(item.pending_tasks_json or []),
                        "linkedPeople": list(item.linked_people_json or []),
                        "lastDigestAt": serialize_datetime(item.last_digest_at),
                        "updatedAt": serialize_datetime(item.updated_at),
                    }
                    for item in chat_items
                ],
            }

    async def rebuild_memory(self, *, reference: str | None = None) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            result = await self._build_memory_service(session).rebuild(reference=reference)
            await session.commit()
            return {
                "updatedChatCount": result.updated_chat_count,
                "updatedPeopleCount": result.updated_people_count,
                "analyzedMessageCount": result.analyzed_message_count,
                "message": result.to_user_message(),
            }

    async def get_digest_overview(self, *, limit: int = 6) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            setting_repository = SettingRepository(session)
            digest_repository = DigestRepository(session)
            recent = await digest_repository.list_recent(limit=limit)
            target = await DigestTargetService(setting_repository).get_target()
            generation_meta = await setting_repository.get_value("digest.last_run_meta")
            return {
                "target": {
                    "chatId": target.chat_id,
                    "label": target.label,
                    "chatType": target.chat_type,
                },
                "latest": serialize_digest(recent[0]) if recent else None,
                "recentRuns": [serialize_digest(item) for item in recent],
                "generation": generation_meta if isinstance(generation_meta, dict) else None,
            }

    async def run_digest(
        self,
        *,
        window: str | None = DEFAULT_DIGEST_WINDOW,
        use_provider_improvement: bool | None = None,
    ) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            service = self._build_digest_service(session)
            plan = await service.build_manual_digest(
                window,
                use_provider_improvement=use_provider_improvement,
            )
            await session.commit()
            digest = (
                await DigestRepository(session).get_digest(plan.digest_id)
                if plan.digest_id is not None
                else None
            )
            return {
                "window": plan.window.label,
                "hasDigest": plan.has_digest,
                "messageCount": plan.message_count,
                "sourceCount": plan.source_count,
                "summaryShort": plan.summary_short,
                "previewChunks": plan.preview_chunks,
                "targetConfigured": plan.target.is_configured,
                "target": {
                    "chatId": plan.target.chat_id,
                    "label": plan.target.label,
                    "chatType": plan.target.chat_type,
                },
                "llmRefineRequested": plan.llm_refine_requested,
                "llmRefineApplied": plan.llm_refine_applied,
                "llmRefineProvider": plan.llm_refine_provider,
                "llmRefineNotes": list(plan.llm_refine_notes),
                "llmRefineGuardrailFlags": list(plan.llm_refine_guardrail_flags),
                "llmDebug": {
                    "mode": (
                        "llm_refine"
                        if plan.llm_refine_applied
                        else "rejected_by_guardrails"
                        if (
                            plan.llm_refine_decision_reason is not None
                            and plan.llm_refine_decision_reason.source == "guardrails"
                        )
                        else "fallback"
                        if plan.llm_refine_requested
                        else "deterministic"
                    ),
                    "baseline": {
                        "summaryShort": plan.llm_refine_baseline_summary_short,
                        "overviewLines": list(plan.llm_refine_baseline_overview_lines),
                        "keySourceLines": list(plan.llm_refine_baseline_key_source_lines),
                    },
                    "rawCandidate": plan.llm_refine_raw_candidate,
                    "decisionReason": (
                        {
                            "source": plan.llm_refine_decision_reason.source,
                            "code": plan.llm_refine_decision_reason.code,
                            "summary": plan.llm_refine_decision_reason.summary,
                            "detail": plan.llm_refine_decision_reason.detail,
                            "flags": list(plan.llm_refine_decision_reason.flags),
                        }
                        if plan.llm_refine_decision_reason is not None
                        else None
                    ),
                },
                "digest": serialize_digest(digest) if digest is not None else None,
            }

    async def set_digest_target(self, *, reference: str | None, label: str | None) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            setting_repository = SettingRepository(session)
            async with self._telegram_resolver() as resolver:
                result = await DigestTargetService(
                    repository=setting_repository,
                    resolver=resolver,
                ).set_target(
                    ParsedDigestTargetCommand(reference=reference, label=label)
                )
            await session.commit()
            return {
                "chatId": result.chat_id,
                "label": result.label,
                "chatType": result.chat_type,
                "note": result.note,
                "message": result.to_user_message(),
            }

    async def get_reminders_overview(self) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            task_repository = TaskRepository(session)
            reminder_repository = ReminderRepository(session)
            return {
                "summary": {
                    "candidateCount": await task_repository.count_candidates(),
                    "confirmedTaskCount": await task_repository.count_confirmed(),
                    "activeReminderCount": await reminder_repository.count_active_reminders(),
                    "lastNotificationAt": serialize_datetime(
                        await reminder_repository.get_last_notification_at()
                    ),
                },
                "candidates": [serialize_task(task) for task in await task_repository.list_candidates()],
                "tasks": [serialize_task(task) for task in await task_repository.list_active_tasks()],
                "reminders": [
                    serialize_reminder(reminder) for reminder in await reminder_repository.list_active_reminders()
                ],
            }

    async def scan_reminders(
        self,
        *,
        window_argument: str | None = None,
        source_reference: str | None = None,
    ) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            result = await self._build_reminder_service(session).scan(
                window_argument=window_argument,
                source_reference=source_reference,
            )
            await session.commit()
            overview = await self.get_reminders_overview()
            return {
                "summaryText": result.summary_text,
                "cards": list(result.cards),
                "createdCount": result.created_count,
                "skippedExistingCount": result.skipped_existing_count,
                "overview": overview,
            }

    async def get_logs(self, *, component: str | None = None, tail: int = DEFAULT_LOG_TAIL) -> dict[str, Any]:
        components = (component,) if component else COMPONENTS
        states = [inspect_process(name) for name in components]
        return {
            "items": [
                {
                    **serialize_process_state(state),
                    "lines": tail_log(state.log_path, lines=max(1, tail)),
                }
                for state in states
            ]
        }

    async def run_operation(self, action: str, *, component: str | None = None) -> dict[str, Any]:
        targets = _resolve_targets(component)
        if action == "start":
            results = [
                start_component(target, python_executable=sys.executable)
                for target in targets
            ]
            return {
                "action": action,
                "results": [
                    {
                        "component": item.component,
                        "ok": item.ok,
                        "started": item.started,
                        "pid": item.pid,
                        "detail": item.detail,
                    }
                    for item in results
                ],
            }

        if action == "stop":
            results = [stop_component(target) for target in _resolve_targets(component, reverse=True)]
            return {
                "action": action,
                "results": [
                    {
                        "component": item.component,
                        "ok": item.ok,
                        "stopped": item.stopped,
                        "pid": item.pid,
                        "detail": item.detail,
                    }
                    for item in results
                ],
            }

        if action == "restart":
            stop_results = [stop_component(target) for target in _resolve_targets(component, reverse=True)]
            start_results = [
                start_component(target, python_executable=sys.executable)
                for target in targets
            ]
            return {
                "action": action,
                "stopResults": [
                    {
                        "component": item.component,
                        "ok": item.ok,
                        "stopped": item.stopped,
                        "pid": item.pid,
                        "detail": item.detail,
                    }
                    for item in stop_results
                ],
                "startResults": [
                    {
                        "component": item.component,
                        "ok": item.ok,
                        "started": item.started,
                        "pid": item.pid,
                        "detail": item.detail,
                    }
                    for item in start_results
                ],
            }

        if action == "backup":
            result = await OperationalBackupService(
                settings=self.settings,
                session_factory=self.runtime.session_factory,
            ).create_backup()
            return {
                "action": action,
                "created": result.created,
                "path": str(result.path),
                "sourcePath": str(result.source_path),
            }

        if action == "export":
            result = await OperationalExportService(
                settings=self.settings,
                session_factory=self.runtime.session_factory,
            ).export_summary()
            return {
                "action": action,
                "path": str(result.path),
                "payload": result.payload,
            }

        if action == "doctor":
            async with self.runtime.session_factory() as session:
                report = await self._build_operational_report(session)
            doctor = SystemHealthService().build_report(report)
            return {
                "action": action,
                "okItems": list(doctor.ok_items),
                "warnings": list(doctor.warnings),
                "nextSteps": list(doctor.next_steps),
            }

        raise ValueError(f"Неизвестная операция: {action}")

    async def _build_operational_report(self, session) -> OperationalReport:
        setting_repository = SettingRepository(session)
        return await SystemReadinessService(
            chat_repository=ChatRepository(session),
            setting_repository=setting_repository,
            system_repository=SystemRepository(session),
            message_repository=MessageRepository(session),
            digest_repository=DigestRepository(session),
            chat_memory_repository=ChatMemoryRepository(session),
            person_memory_repository=PersonMemoryRepository(session),
            style_profile_repository=StyleProfileRepository(session),
            chat_style_override_repository=ChatStyleOverrideRepository(session),
            task_repository=TaskRepository(session),
            reminder_repository=ReminderRepository(session),
            reply_example_repository=ReplyExampleRepository(session),
            provider_manager=ProviderManager.from_settings(
                self.settings,
                setting_repository=setting_repository,
            ),
            fullaccess_auth_service=FullAccessAuthService(
                settings=self.settings,
                setting_repository=setting_repository,
                message_repository=MessageRepository(session),
            ),
            settings=self.settings,
        ).build_report()

    def _build_status_service(self, session) -> BotStatusService:
        setting_repository = SettingRepository(session)
        return BotStatusService(
            chat_repository=ChatRepository(session),
            setting_repository=setting_repository,
            system_repository=SystemRepository(session),
            message_repository=MessageRepository(session),
            digest_repository=DigestRepository(session),
            chat_memory_repository=ChatMemoryRepository(session),
            person_memory_repository=PersonMemoryRepository(session),
            style_profile_repository=StyleProfileRepository(session),
            chat_style_override_repository=ChatStyleOverrideRepository(session),
            task_repository=TaskRepository(session),
            reminder_repository=ReminderRepository(session),
            reply_example_repository=ReplyExampleRepository(session),
            provider_manager=ProviderManager.from_settings(
                self.settings,
                setting_repository=setting_repository,
            ),
            fullaccess_auth_service=FullAccessAuthService(
                settings=self.settings,
                setting_repository=setting_repository,
                message_repository=MessageRepository(session),
            ),
            settings=self.settings,
        )

    def _build_fullaccess_auth_service(self, session) -> FullAccessAuthService:
        return FullAccessAuthService(
            settings=self.settings,
            setting_repository=SettingRepository(session),
            message_repository=MessageRepository(session),
        )

    def _build_fullaccess_sync_service(self, session) -> FullAccessSyncService:
        return FullAccessSyncService(
            settings=self.settings,
            chat_repository=ChatRepository(session),
            message_repository=MessageRepository(session),
            setting_repository=SettingRepository(session),
        )

    def _build_fullaccess_send_service(self, session) -> FullAccessSendService:
        return FullAccessSendService(
            settings=self.settings,
            chat_repository=ChatRepository(session),
            message_repository=MessageRepository(session),
            setting_repository=SettingRepository(session),
        )

    def _build_autopilot_service(self, session) -> AutopilotService:
        setting_repository = SettingRepository(session)
        return AutopilotService(
            chat_repository=ChatRepository(session),
            setting_repository=setting_repository,
            send_service=self._build_fullaccess_send_service(session),
            journal=WorkflowJournalService(setting_repository),
        )

    def _build_memory_service(self, session) -> MemoryService:
        return MemoryService(
            chat_repository=ChatRepository(session),
            message_repository=MessageRepository(session),
            digest_repository=DigestRepository(session),
            setting_repository=SettingRepository(session),
            chat_memory_repository=ChatMemoryRepository(session),
            person_memory_repository=PersonMemoryRepository(session),
            chat_builder=ChatMemoryBuilder(),
            people_builder=PeopleMemoryBuilder(),
            formatter=MemoryFormatter(),
        )

    async def _legacy_build_reply_result(
        self,
        session,
        reference: str,
        *,
        use_provider_refinement: bool | None = None,
        workspace_messages=None,
    ):
        # LEGACY_RUNTIME: this is the old reply core boundary. Do not add new
        # product behavior here; implement DraftReplyWorkspace on the new runtime.
        service = self._build_reply_service(session)
        if workspace_messages is None:
            return await service.build_reply(
                reference,
                use_provider_refinement=use_provider_refinement,
            )
        return await service.build_reply(
            reference,
            use_provider_refinement=use_provider_refinement,
            workspace_messages=workspace_messages,
        )

    def _build_reply_service(self, session) -> ReplyEngineService:
        message_repository = MessageRepository(session)
        chat_memory_repository = ChatMemoryRepository(session)
        person_memory_repository = PersonMemoryRepository(session)
        setting_repository = SettingRepository(session)
        provider_manager = ProviderManager.from_settings(
            self.settings,
            setting_repository=setting_repository,
        )
        return ReplyEngineService(
            chat_repository=ChatRepository(session),
            message_repository=message_repository,
            chat_memory_repository=chat_memory_repository,
            person_memory_repository=person_memory_repository,
            context_builder=ReplyContextBuilder(
                message_repository=message_repository,
                chat_memory_repository=chat_memory_repository,
                person_memory_repository=person_memory_repository,
            ),
            classifier=ReplyClassifier(),
            strategy_resolver=ReplyStrategyResolver(),
            style_selector=StyleSelectorService(
                style_profile_repository=StyleProfileRepository(session),
                chat_style_override_repository=ChatStyleOverrideRepository(session),
                chat_memory_repository=chat_memory_repository,
                person_memory_repository=person_memory_repository,
            ),
            style_adapter=StyleAdapter(),
            persona_core_service=PersonaCoreService(setting_repository),
            persona_adapter=PersonaAdapter(),
            persona_guardrails=PersonaGuardrails(),
            reply_examples_retriever=ReplyExamplesRetriever(
                reply_example_repository=ReplyExampleRepository(session),
            ),
            reply_refiner=ReplyLLMRefiner(provider_manager=provider_manager),
            setting_repository=setting_repository,
        )

    def _build_digest_service(self, session) -> DigestEngineService:
        setting_repository = SettingRepository(session)
        provider_manager = ProviderManager.from_settings(
            self.settings,
            setting_repository=setting_repository,
        )
        return DigestEngineService(
            message_repository=MessageRepository(session),
            digest_repository=DigestRepository(session),
            setting_repository=setting_repository,
            builder=DigestBuilder(),
            formatter=DigestFormatter(),
            digest_refiner=DigestLLMRefiner(provider_manager=provider_manager),
        )

    def _build_reminder_service(self, session) -> ReminderService:
        return ReminderService(
            chat_repository=ChatRepository(session),
            message_repository=MessageRepository(session),
            chat_memory_repository=ChatMemoryRepository(session),
            setting_repository=SettingRepository(session),
            task_repository=TaskRepository(session),
            reminder_repository=ReminderRepository(session),
            extractor=ReminderExtractor(),
            formatter=ReminderFormatter(),
        )

    async def _build_workspace_payload(
        self,
        session,
        *,
        chat,
        limit: int,
        tail_refresh: ChatTailRefreshStatus | None = None,
    ) -> dict[str, Any]:
        message_repository = MessageRepository(session)
        fullaccess_status = await self._build_fullaccess_auth_service(session).build_status_report()
        recent_desc = await message_repository.get_recent_messages(chat_id=chat.id, limit=max(1, limit))
        messages = list(reversed(recent_desc))
        last_message = recent_desc[0] if recent_desc else None
        message_count = await message_repository.count_messages_for_chat(chat_id=chat.id)
        reply_result = await self._runtime_manager.surface("replyGeneration").build_reply_result(
            build_chat_reference(chat),
            workspace_messages=tuple(messages),
        )
        freshness = await self._build_chat_freshness(
            session,
            chat=chat,
            last_message=last_message,
            tail_refresh=tail_refresh,
        )
        autopilot = await self._build_autopilot_service(session).build_chat_overview(
            chat=chat,
            reply_result=reply_result,
            write_ready=fullaccess_status.ready_for_manual_send,
        )
        return {
            "chat": serialize_chat(
                chat,
                message_count=message_count,
                last_message=last_message,
                session_file=self.settings.fullaccess_session_file,
            ),
            "messages": [
                serialize_message(
                    message,
                    session_file=self.settings.fullaccess_session_file,
                    telegram_chat_id=chat.telegram_chat_id,
                )
                for message in messages
            ],
            "reply": self._decorate_reply_payload(
                serialize_reply_result(reply_result),
                write_ready=fullaccess_status.ready_for_manual_send,
            ),
            "autopilot": autopilot,
            "freshness": freshness,
            "refreshedAt": serialize_datetime(datetime.now(timezone.utc)),
        }

    def _decorate_reply_payload(
        self,
        payload: dict[str, Any],
        *,
        write_ready: bool,
    ) -> dict[str, Any]:
        payload["actions"] = {
            "copy": True,
            "refresh": True,
            "pasteToTelegram": False,
            "send": write_ready,
            "markSent": True,
            "variants": {
                "short": True,
                "normal": True,
                "softer": True,
                "harder": False,
                "myStyle": True,
            },
            "disabledReason": None if write_ready else "Write-path через full-access сейчас недоступен.",
        }
        return payload

    async def _maybe_refresh_chat_tail(self, session, *, chat) -> ChatTailRefreshStatus:
        if chat.category != "fullaccess":
            return ChatTailRefreshStatus(attempted=False, updated=False)

        setting_repository = SettingRepository(session)
        status = await self._build_fullaccess_auth_service(session).build_status_report()
        if not status.ready_for_manual_sync:
            return ChatTailRefreshStatus(attempted=False, updated=False)

        sync_event = await OperationalStateService(setting_repository).get_fullaccess_chat_sync(chat.id)
        if sync_event is not None and sync_event.timestamp is not None:
            age_seconds = max(
                0,
                int((datetime.now(timezone.utc) - sync_event.timestamp).total_seconds()),
            )
            if age_seconds < AUTO_WORKSPACE_SYNC_MIN_SECONDS:
                return ChatTailRefreshStatus(
                    attempted=False,
                    updated=False,
                    trigger=str(sync_event.payload.get("trigger") or "manual"),
                )

        try:
            await self._build_fullaccess_sync_service(session).sync_chat(
                build_chat_reference(chat),
                trigger="auto",
            )
        except ValueError as error:
            await session.rollback()
            return ChatTailRefreshStatus(
                attempted=True,
                updated=False,
                error=str(error),
                trigger="auto",
            )

        await session.commit()
        return ChatTailRefreshStatus(attempted=True, updated=True, trigger="auto")

    async def _build_chat_freshness(self, session, *, chat, last_message, tail_refresh: ChatTailRefreshStatus | None = None) -> dict[str, Any]:
        is_fullaccess_chat = chat.category == "fullaccess" or (
            last_message is not None and last_message.source_adapter == "fullaccess"
        )
        if not is_fullaccess_chat:
            return {
                "mode": "local",
                "label": "Локальный контекст",
                "detail": "Этот чат питается локальным message store без full-access sync.",
                "isStale": False,
                "fullaccessReady": False,
                "canManualSync": False,
                "lastSyncAt": None,
                "reference": build_chat_reference(chat),
                "createdCount": 0,
                "updatedCount": 0,
                "skippedCount": 0,
                "syncTrigger": None,
                "updatedNow": False,
                "syncError": None,
            }

        setting_repository = SettingRepository(session)
        status = await self._build_fullaccess_auth_service(session).build_status_report()
        sync_event = await OperationalStateService(setting_repository).get_fullaccess_chat_sync(chat.id)
        sync_payload = sync_event.payload if sync_event is not None else {}
        last_sync_at = sync_event.timestamp if sync_event is not None else None

        mode = "fresh"
        label = "Контекст свежий"
        is_stale = False
        detail = "Последний full-access sync был недавно, reply строится по свежему хвосту."
        sync_trigger = (
            str(sync_payload.get("trigger"))
            if sync_payload.get("trigger") is not None
            else tail_refresh.trigger if tail_refresh is not None else None
        )
        sync_error = tail_refresh.error if tail_refresh is not None else None
        updated_now = bool(tail_refresh is not None and tail_refresh.updated)

        if sync_error:
            mode = "attention"
            label = "Авто-sync не удался"
            is_stale = True
            detail = (
                f"Автообновление временно не удалось: {sync_error}. "
                "Показан последний локальный хвост без падения shell."
            )
        elif updated_now:
            label = "Хвост обновлён"
            detail = "Активный чат только что дочитан через full-access, reply строится по свежему хвосту."
        elif not status.ready_for_manual_sync:
            mode = "attention"
            label = "Full-access требует внимания"
            is_stale = True
            detail = status.reason or "Full-access сейчас не готов."
        elif sync_event is None or last_sync_at is None:
            mode = "missing"
            label = "Нужна первая синхронизация"
            is_stale = True
            detail = "Для этого чата ещё нет успешного full-access sync, свежий хвост не подтверждён."
        else:
            age_seconds = max(
                0,
                int((datetime.now(timezone.utc) - last_sync_at).total_seconds()),
            )
            if age_seconds > 180:
                mode = "stale"
                label = "Контекст может устареть"
                is_stale = True
                detail = "Последний full-access sync был давно, лучше освежить чат перед ответом."
            elif age_seconds > 60:
                mode = "aging"
                label = "Контекст скоро состарится"
                detail = "Свежий хвост уже подтягивался, но лучше держать sync под рукой."

        return {
            "mode": mode,
            "label": label,
            "detail": detail,
            "isStale": is_stale,
            "fullaccessReady": status.ready_for_manual_sync,
            "canManualSync": status.ready_for_manual_sync,
            "lastSyncAt": serialize_datetime(last_sync_at),
            "reference": (
                str(sync_payload.get("reference"))
                if sync_payload.get("reference") is not None
                else build_chat_reference(chat)
            ),
            "createdCount": int(sync_payload.get("created_count") or 0),
            "updatedCount": int(sync_payload.get("updated_count") or 0),
            "skippedCount": int(sync_payload.get("skipped_count") or 0),
            "syncTrigger": sync_trigger,
            "updatedNow": updated_now,
            "syncError": sync_error,
        }

    @asynccontextmanager
    async def _telegram_resolver(self) -> AsyncIterator[TelegramChatResolver | None]:
        token = (self.settings.telegram_bot_token or "").strip()
        if not token:
            yield None
            return

        bot = Bot(token=token)
        try:
            yield TelegramChatResolver(bot=bot)
        finally:
            await bot.session.close()

    def _build_status_cards(
        self,
        *,
        facts: OperationalFacts,
        process_states,
        database,
        runtime_status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        process_lookup = {item.component: item for item in process_states}
        fullaccess_status = facts.fullaccess_status
        new_runtime = runtime_status.get("newRuntime")
        new_runtime_payload = new_runtime if isinstance(new_runtime, dict) else {}
        runtime_ready = bool(new_runtime_payload.get("ready"))
        runtime_active = bool(new_runtime_payload.get("active"))
        runtime_detail = (
            str(new_runtime_payload.get("degradedReason") or new_runtime_payload.get("unavailableReason") or "OK")
            if new_runtime_payload
            else "New runtime status недоступен."
        )
        return [
            {
                "key": "bot",
                "label": "Бот",
                "status": "online" if process_lookup["bot"].running else "offline",
                "value": "работает" if process_lookup["bot"].running else "остановлен",
                "detail": process_lookup["bot"].detail,
            },
            {
                "key": "worker",
                "label": "Worker",
                "status": "online" if process_lookup["worker"].running else "offline",
                "value": "работает" if process_lookup["worker"].running else "остановлен",
                "detail": process_lookup["worker"].detail,
            },
            {
                "key": "provider",
                "label": "Провайдер",
                "status": (
                    "online"
                    if facts.provider_status.reply_refine_available or facts.provider_status.digest_refine_available
                    else "muted"
                    if not facts.provider_status.enabled
                    else "warning"
                ),
                "value": facts.provider_status.provider_name or "deterministic",
                "detail": facts.provider_status.reason,
            },
            {
                "key": "fullaccess",
                "label": "Full-access",
                "status": (
                    "online"
                    if fullaccess_status and fullaccess_status.ready_for_manual_sync
                    else "muted"
                    if not fullaccess_status or not fullaccess_status.enabled
                    else "warning"
                ),
                "value": (
                    "готов"
                    if fullaccess_status and fullaccess_status.ready_for_manual_sync
                    else "выключен"
                    if not fullaccess_status or not fullaccess_status.enabled
                    else "требует вход"
                ),
                "detail": fullaccess_status.reason if fullaccess_status is not None else "Слой выключен.",
            },
            {
                "key": "newRuntime",
                "label": "New runtime",
                "status": "online" if runtime_ready else "warning" if runtime_active else "muted",
                "value": "готов" if runtime_ready else "активен" if runtime_active else "inactive",
                "detail": runtime_detail,
            },
            {
                "key": "db",
                "label": "База",
                "status": "online" if database.available else "warning",
                "value": "доступна" if database.available else "недоступна",
                "detail": database.detail,
            },
            {
                "key": "sources",
                "label": "Источники",
                "status": "online" if facts.active_sources else "warning",
                "value": f"{facts.active_sources}/{facts.total_sources}",
                "detail": f"Сообщений: {facts.total_messages}",
            },
            {
                "key": "memory",
                "label": "Память",
                "status": "online" if facts.has_memory_cards else "warning",
                "value": str(facts.chat_memory_cards + facts.person_memory_cards),
                "detail": "Чаты и люди",
            },
            {
                "key": "digest",
                "label": "Дайджест",
                "status": "online" if facts.total_digests else "warning",
                "value": facts.digest_target_label or "получатель не задан",
                "detail": f"Последний запуск: {serialize_datetime(facts.last_digest_at) or 'ещё не было'}",
            },
            {
                "key": "reminders",
                "label": "Напоминания",
                "status": "online" if facts.active_reminders else "muted",
                "value": str(facts.active_reminders),
                "detail": "Активные напоминания",
            },
        ]

    def _build_attention_items(self, report: OperationalReport) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for text in report.next_steps[:4]:
            items.append({"tone": "warning", "text": text})
        for text in report.warnings[:4]:
            items.append({"tone": "muted", "text": text})
        return items[:6]

    def _build_activity_items(
        self,
        facts: OperationalFacts,
        last_digest,
    ) -> list[dict[str, Any]]:
        candidates = [
            _event_item(facts.last_message_at, "Последнее сообщение", "В локальной базе появились новые данные."),
            _event_item(facts.last_digest_at, "Последний дайджест", facts.digest_target_label or "Получатель пока не задан."),
            _event_item(facts.last_memory_rebuild_at, "Пересборка памяти", "Memory-слой был обновлён."),
            _event_item(facts.last_reminder_notification, "Delivery reminders", "Worker отправлял напоминания."),
            _event_item(facts.last_fullaccess_sync_at, "Full-access sync", "История была дочитана вручную."),
            _event_item(facts.last_backup_at, "Backup", facts.last_backup_path or "Создан свежий backup."),
            _event_item(facts.last_export_at, "Export", facts.last_export_path or "Сохранён operational export."),
            _event_item(
                last_digest.created_at if last_digest is not None else None,
                "Сводка сохранена",
                last_digest.summary_short if last_digest is not None else None,
            ),
        ]
        items = [item for item in candidates if item is not None]
        items.sort(key=lambda item: item["timestamp"] or "", reverse=True)
        return items[:8]

    def _build_error_items(
        self,
        facts: OperationalFacts,
        database_available: bool,
        provider_available: bool,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not database_available:
            items.append({"tone": "danger", "title": "База данных", "text": "Bridge не может подтвердить доступ к базе."})
        if facts.recent_worker_error:
            items.append({"tone": "danger", "title": "Worker", "text": facts.recent_worker_error})
        if facts.recent_provider_error:
            items.append({"tone": "danger", "title": "Provider", "text": facts.recent_provider_error})
        if facts.recent_fullaccess_error:
            items.append({"tone": "warning", "title": "Full-access", "text": facts.recent_fullaccess_error})
        if facts.provider_status.enabled and not provider_available:
            items.append({"tone": "warning", "title": "Provider", "text": facts.provider_status.reason})
        items.extend(
            {"tone": "warning", "title": "Startup", "text": warning}
            for warning in facts.startup_warnings[:4]
        )
        if not items:
            items.append({"tone": "success", "title": "Ошибок не видно", "text": "Критичных operational-сигналов сейчас нет."})
        return items[:8]

    def _build_now_items(self, facts: OperationalFacts, process_states) -> list[str]:
        process_lookup = {item.component: item for item in process_states}
        items: list[str] = []
        if process_lookup["bot"].running:
            items.append(f"Бот слушает {facts.active_sources} активных источников.")
        else:
            items.append("Бот сейчас не запущен.")

        if process_lookup["worker"].running:
            items.append("Worker следит за фоновыми задачами и delivery reminders.")
        else:
            items.append("Worker остановлен, фоновые циклы сейчас не крутятся.")

        if facts.reply_ready_chats:
            items.append(f"Reply уже можно собирать минимум по {facts.reply_ready_chats} чатам.")
        if facts.fullaccess_status and facts.fullaccess_status.ready_for_manual_sync:
            items.append("Full-access готов к ручной синхронизации нужных чатов.")
        return items[:4]


async def _load_last_message(message_repository: MessageRepository, chat_id: int) -> Message | None:
    recent = await message_repository.get_recent_messages(chat_id=chat_id, limit=1)
    if not recent:
        return None
    return recent[0]


def _event_item(timestamp_value, title: str, detail: str | None) -> dict[str, Any] | None:
    timestamp = serialize_datetime(timestamp_value)
    if timestamp is None:
        return None
    return {
        "timestamp": timestamp,
        "title": title,
        "detail": detail,
    }


def _resolve_targets(component: str | None, *, reverse: bool = False) -> list[str]:
    if component is not None:
        if component not in COMPONENTS:
            raise ValueError(f"Неизвестный component: {component}")
        return [component]
    targets = list(COMPONENTS)
    if reverse:
        targets.reverse()
    return targets
