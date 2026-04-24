from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, cast

from aiogram import Bot

from astra_runtime.chat_identity import ChatIdentity, parse_runtime_only_chat_id
from astra_runtime.message_identity import parse_message_key
from astra_runtime.contracts import TelegramRuntime
from astra_runtime.legacy import LegacyAstraRuntime
from astra_runtime.manager import LegacyRuntimeBackend, RuntimeManager, StaticRuntimeBackend
from astra_runtime.new_telegram import (
    DatabaseNewTelegramAuthSessionStore,
    NewTelegramRuntimeConfig,
    NewTelegramRuntimeService,
)
from astra_runtime.status import RuntimeUnavailableError
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
from core.logging import get_logger, log_event
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
from services.reply_execution import (
    ReplyExecutionActionError,
    ReplyExecutionService,
    normalize_reply_execution_mode,
)
from services.people_memory_builder import PeopleMemoryBuilder
from services.providers.digest_refiner import DigestLLMRefiner
from services.providers.manager import ProviderManager
from services.reply_payload import build_reply_context_payload, decorate_reply_payload
from services.reminder_extractor import ReminderExtractor
from services.reminder_formatter import ReminderFormatter
from services.reminder_service import ReminderService
from services.reply_engine import ReplyEngineService
from services.reply_service_factory import build_reply_service
from services.source_registry import SourceRegistryService
from services.status_summary import BotStatusService
from services.system_health import SystemHealthService
from services.system_readiness import OperationalFacts, OperationalReport, SystemReadinessService
from services.telegram_lookup import TelegramChatResolver
from services.workflow_journal import WorkflowJournalService, build_workflow_event
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

from .live import DesktopLiveCoordinator, LiveRefreshResult
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
MANUAL_SEND_DUPLICATE_WINDOW_SECONDS = 3
LOGGER = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatTailRefreshStatus:
    attempted: bool
    updated: bool
    error: str | None = None
    trigger: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedChatHandle:
    requested_chat_id: int
    local_chat_id: int | None
    runtime_chat_id: int | None


@dataclass(frozen=True, slots=True)
class ManualSendTarget:
    requested_chat_id: int
    local_chat_id: int | None
    runtime_chat_id: int | None

    @property
    def chat_key(self) -> str | None:
        if self.runtime_chat_id is None:
            return None
        return ChatIdentity(
            runtime_chat_id=self.runtime_chat_id,
            local_chat_id=self.local_chat_id,
        ).chat_key


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
    _live_coordinator: DesktopLiveCoordinator = field(default_factory=DesktopLiveCoordinator, init=False, repr=False)
    _manual_send_inflight: set[str] = field(default_factory=set, init=False, repr=False)
    _manual_send_recent_success_at: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)

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
            settings=self.settings,
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
        status["chatRoster"] = await self._get_chat_roster_state()
        status["messageWorkspace"] = await self._get_message_workspace_state()
        status["manualSend"] = await self._get_manual_send_state()
        try:
            status["autopilot"] = await self.get_autopilot_status()
        except RuntimeUnavailableError as error:
            status["autopilot"] = _build_unavailable_surface_status(
                route=self._runtime_manager.route_status("autopilotControl").to_payload(),
                reason=str(error),
                code=error.code,
            )
        status["live"] = await self._get_live_status()
        return status

    async def get_new_runtime_health(self) -> dict[str, Any]:
        return await self._runtime_manager.health("new")

    async def get_new_runtime_auth_status(self) -> dict[str, Any]:
        service = self._require_new_runtime_service()
        status = await service.auth_status()
        return {"status": status.to_payload()}

    async def request_new_runtime_code(self) -> dict[str, Any]:
        service = self._require_new_runtime_service()
        return (await service.request_code()).to_payload()

    async def submit_new_runtime_code(self, *, code: str) -> dict[str, Any]:
        service = self._require_new_runtime_service()
        return (await service.submit_code(code)).to_payload()

    async def submit_new_runtime_password(self, *, password: str) -> dict[str, Any]:
        service = self._require_new_runtime_service()
        return (await service.submit_password(password)).to_payload()

    async def logout_new_runtime(self) -> dict[str, Any]:
        service = self._require_new_runtime_service()
        return (await service.logout()).to_payload()

    async def reset_new_runtime(self) -> dict[str, Any]:
        service = self._require_new_runtime_service()
        return (await service.reset()).to_payload()

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
        route = self._runtime_manager.route_status("chatRoster")
        try:
            payload = await self._runtime_manager.surface("chatRoster").list_chats(
                search=search,
                filter_key=filter_key,
                sort_key=sort_key,
            )
        except RuntimeUnavailableError:
            raise
        except Exception as error:
            if route.requested == "new":
                route_payload = route.to_payload()
                route_payload["status"] = "unavailable"
                route_payload["reason"] = str(error)
                route_payload["reasonCode"] = "degraded"
                route_payload["actionHint"] = "Обнови runtime и повтори загрузку списка."
                await self._record_chat_roster_state(
                    self._build_chat_roster_state(
                        route=route_payload,
                        source="new",
                        effective_backend="new",
                        refreshed_at=None,
                        runtime_meta={},
                        last_error=str(error),
                    )
                )
                raise RuntimeUnavailableError(
                    str(error),
                    code="degraded",
                    action_hint="Обнови runtime и повтори загрузку списка.",
                ) from error
            raise

        source = _resolve_runtime_surface_source(
            requested=route.requested,
            effective=route.effective,
        )
        runtime_meta = payload.get("runtimeMeta") if isinstance(payload.get("runtimeMeta"), dict) else {}
        payload.pop("runtimeMeta", None)
        route_payload = route.to_payload()
        roster_state = self._build_chat_roster_state(
            route=route_payload,
            source=source,
            effective_backend=route.effective,
            refreshed_at=payload.get("refreshedAt"),
            runtime_meta=runtime_meta,
            last_error=None,
        )
        payload["source"] = source
        payload["roster"] = roster_state
        await self._record_chat_roster_state(roster_state)
        return payload

    async def get_live_roster(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
        force: bool = False,
        reason: str = "poll",
    ) -> dict[str, Any]:
        result = await self._live_coordinator.refresh_roster(
            fetch_roster=lambda: self.list_chats(
                search=search,
                filter_key=filter_key,
                sort_key=sort_key,
            ),
            force=force,
            reason=reason,
            cache_key=_live_roster_cache_key(search=search, filter_key=filter_key, sort_key=sort_key),
        )
        await self._record_live_result(result)
        return result.payload

    async def refresh_live_roster(
        self,
        *,
        search: str | None = None,
        filter_key: str = "all",
        sort_key: str = "activity",
    ) -> dict[str, Any]:
        return await self.get_live_roster(
            search=search,
            filter_key=filter_key,
            sort_key=sort_key,
            force=True,
            reason="manual_refresh",
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
                        asset_session_files=self._asset_session_files(),
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

    async def get_chat_workspace(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        execute_reply_modes: bool = True,
    ) -> dict[str, Any]:
        route = self._runtime_manager.route_status("messageWorkspace")
        try:
            payload = await self._runtime_manager.surface("messageWorkspace").get_chat_workspace(
                chat_id,
                limit=limit,
            )
        except RuntimeUnavailableError:
            raise
        except Exception as error:
            if route.requested == "new":
                route_payload = route.to_payload()
                route_payload["status"] = "unavailable"
                route_payload["reason"] = str(error)
                route_payload["reasonCode"] = "degraded"
                route_payload["actionHint"] = "Повтори обновление workspace через новый runtime."
                await self._record_message_workspace_state(
                    _build_unavailable_workspace_status(route=route_payload)
                )
                raise RuntimeUnavailableError(
                    str(error),
                    code="degraded",
                    action_hint="Повтори обновление workspace через новый runtime.",
                ) from error
            raise

        source = _resolve_runtime_surface_source(
            requested=route.requested,
            effective=route.effective,
        )
        status_payload = self._decorate_workspace_status_payload(
            payload=payload,
            route=route.to_payload(),
            source=source,
            effective_backend=route.effective,
            last_error=None,
        )
        await self._record_message_workspace_state(status_payload)
        if execute_reply_modes:
            execution = await self._apply_reply_execution_to_workspace(
                chat_id,
                payload=payload,
                limit=limit,
            )
            if execution is not None and execution.get("workspace") is not None:
                return execution["workspace"]
        return payload

    async def get_live_chat_workspace(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        force: bool = False,
        reason: str = "poll",
    ) -> dict[str, Any]:
        result = await self._live_coordinator.refresh_active_chat(
            chat_id=chat_id,
            fetch_workspace=lambda: self.get_chat_workspace(
                chat_id,
                limit=limit,
                execute_reply_modes=False,
            ),
            fetch_messages=lambda: self.get_chat_messages(chat_id, limit=limit),
            force=force,
            reason=reason,
        )
        payload = result.payload
        if result.execute_reply_modes:
            execution = await self._apply_reply_execution_to_workspace(
                chat_id,
                payload=payload,
                limit=limit,
                actor="desktop_live",
            )
            if execution is not None and execution.get("workspace") is not None:
                refreshed = execution["workspace"]
                if isinstance(refreshed, dict):
                    refreshed["live"] = payload.get("live")
                    if isinstance(refreshed.get("status"), dict) and isinstance(payload.get("live"), dict):
                        refreshed["status"]["live"] = payload["live"]
                    payload = refreshed
            self._live_coordinator.update_active_payload(chat_id=chat_id, workspace=payload)
        _decorate_live_autopilot_status(payload)
        live_event = payload.get("live") if isinstance(payload.get("live"), dict) else result.event
        await self._record_live_event(live_event, chat_id=chat_id)
        return payload

    async def refresh_live_chat_workspace(
        self,
        chat_id: int,
        *,
        limit: int = 80,
    ) -> dict[str, Any]:
        return await self.get_live_chat_workspace(
            chat_id,
            limit=limit,
            force=True,
            reason="manual_refresh",
        )

    async def pause_live_active_chat(self, chat_id: int, *, paused: bool) -> dict[str, Any]:
        event = self._live_coordinator.pause_active_chat(chat_id=chat_id, paused=paused)
        await self._record_live_event(event, chat_id=chat_id)
        return {
            "ok": True,
            "live": event,
        }

    async def clear_live_errors(self, *, chat_id: int | None = None) -> dict[str, Any]:
        event = self._live_coordinator.clear_errors(chat_id=chat_id)
        await self._record_live_event(event, chat_id=chat_id)
        return {
            "ok": True,
            "live": event,
        }

    async def list_live_activity(self, *, limit: int = 12) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            items = await OperationalStateService(SettingRepository(session)).list_live_activity(limit=limit)
        return {"items": list(items), "count": len(items)}

    async def _legacy_get_chat_workspace(self, chat_id: int, *, limit: int = 80) -> dict[str, Any]:
        # LEGACY_RUNTIME: workspace refresh still uses fullaccess tail sync.
        # Future message workspace implementations should live behind MessageHistory.
        async with self.runtime.session_factory() as session:
            chat = await self._require_local_chat(
                session,
                chat_id,
                runtime_only_message=(
                    "История этого чата пока живёт только в runtime roster. "
                    "Сначала подтяни его через sync."
                ),
            )
            local_chat_id = chat.id

            tail_refresh = await self._maybe_refresh_chat_tail(session, chat=chat)
            if tail_refresh.error:
                chat = await self._require_local_chat(
                    session,
                    local_chat_id,
                    runtime_only_message="Чат пропал из локального storage после refresh.",
                )
            return await self._build_workspace_payload(
                session,
                chat=chat,
                limit=limit,
                tail_refresh=tail_refresh,
            )

    async def _apply_reply_execution_to_workspace(
        self,
        chat_id: int,
        *,
        payload: dict[str, Any],
        limit: int,
        actor: str = "desktop",
    ) -> dict[str, Any] | None:
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            run = await service.evaluate_workspace(
                requested_chat_id=chat_id,
                workspace_payload=payload,
                actor=actor,
            )
            payload["autopilot"] = run.autopilot
            await OperationalStateService(SettingRepository(session)).record_reply_execution(
                payload={
                    "chatKey": run.autopilot.get("policy", {}).get("chat", {}).get("chatKey")
                    if isinstance(run.autopilot.get("policy"), dict)
                    else None,
                    "decision": run.decision.to_payload(),
                    "autopilot": run.autopilot,
                },
            )
            await session.commit()
            if run.pending_send is None:
                return {"workspace": None, "autopilot": run.autopilot}
            chat_policy = await service.get_chat_policy_for_payload(
                requested_chat_id=chat_id,
                chat_payload=payload.get("chat") if isinstance(payload.get("chat"), dict) else None,
            )
            state = await service._load_state(chat_policy.chat_key)
            pending = run.pending_send

        try:
            send_payload = await self._send_reply_execution_via_new_send_path(chat_id, pending=pending)
        except Exception as error:
            async with self.runtime.session_factory() as session:
                service = self._build_reply_execution_service(session)
                state = await service.mark_failed(
                    chat_policy=chat_policy,
                    state=state,
                    pending=pending,
                    error=str(error),
                    actor=actor,
                    automatic=True,
                )
                fallback_decision = await service.get_status_payload(
                    requested_chat_id=chat_id,
                    chat_payload=payload.get("chat") if isinstance(payload.get("chat"), dict) else None,
                )
                await OperationalStateService(SettingRepository(session)).record_reply_execution(
                    payload=fallback_decision,
                )
                await session.commit()
            payload["autopilot"] = fallback_decision.get("autopilot")
            return {"workspace": None, "autopilot": payload["autopilot"]}

        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            state = await service.mark_sent(
                chat_policy=chat_policy,
                state=state,
                pending=pending,
                sent_payload=send_payload,
                actor=actor,
                automatic=True,
            )
            status = await service.get_status_payload(
                requested_chat_id=chat_id,
                chat_payload=payload.get("chat") if isinstance(payload.get("chat"), dict) else None,
            )
            await OperationalStateService(SettingRepository(session)).record_reply_execution(payload=status)
            await session.commit()

        workspace = await self.get_chat_workspace(
            chat_id,
            limit=limit,
            execute_reply_modes=False,
        )
        workspace["autopilot"] = status.get("autopilot")
        return {"workspace": workspace, "state": state}

    async def _send_reply_execution_via_new_send_path(
        self,
        chat_id: int,
        *,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        route = self._runtime_manager.route_status("sendPath").to_payload()
        if route.get("effective") != "new":
            raise RuntimeUnavailableError(
                route.get("reason")
                if isinstance(route.get("reason"), str)
                else "New runtime send-path is required for reply execution."
            )
        text = pending.get("text") if isinstance(pending.get("text"), str) else ""
        source_message_id = (
            pending.get("sourceMessageId")
            if isinstance(pending.get("sourceMessageId"), int)
            else pending.get("source_message_id")
            if isinstance(pending.get("source_message_id"), int)
            else None
        )
        source_message_key = (
            pending.get("sourceMessageKey")
            if isinstance(pending.get("sourceMessageKey"), str)
            else pending.get("source_message_key")
            if isinstance(pending.get("source_message_key"), str)
            else None
        )
        draft_scope_key = (
            pending.get("draftScopeKey")
            if isinstance(pending.get("draftScopeKey"), str)
            else pending.get("draft_scope_key")
            if isinstance(pending.get("draft_scope_key"), str)
            else None
        )
        client_send_id = (
            pending.get("executionId")
            if isinstance(pending.get("executionId"), str)
            else pending.get("execution_id")
            if isinstance(pending.get("execution_id"), str)
            else None
        )
        return await self._runtime_manager.surface("sendPath").send_chat_message(
            chat_id,
            text=text,
            source_message_id=source_message_id,
            reply_to_source_message_id=source_message_id,
            source_message_key=source_message_key,
            reply_to_source_message_key=source_message_key,
            draft_scope_key=draft_scope_key,
            client_send_id=client_send_id,
        )

    async def get_chat_messages(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        before_runtime_message_id: int | None = None,
    ) -> dict[str, Any]:
        route = self._runtime_manager.route_status("messageWorkspace")
        try:
            payload = await self._runtime_manager.surface("messageWorkspace").get_chat_messages(
                chat_id,
                limit=limit,
                before_runtime_message_id=before_runtime_message_id,
            )
        except RuntimeUnavailableError:
            raise
        except Exception as error:
            if route.requested == "new":
                route_payload = route.to_payload()
                route_payload["status"] = "unavailable"
                route_payload["reason"] = str(error)
                route_payload["reasonCode"] = "degraded"
                route_payload["actionHint"] = "Повтори чтение истории через новый runtime."
                await self._record_message_workspace_state(
                    _build_unavailable_workspace_status(route=route_payload)
                )
                raise RuntimeUnavailableError(
                    str(error),
                    code="degraded",
                    action_hint="Повтори чтение истории через новый runtime.",
                ) from error
            raise

        self._decorate_workspace_status_payload(
            payload=payload,
            route=route.to_payload(),
            source=_resolve_runtime_surface_source(
                requested=route.requested,
                effective=route.effective,
            ),
            effective_backend=route.effective,
            last_error=None,
        )
        return payload

    async def _legacy_get_chat_messages(
        self,
        chat_id: int,
        *,
        limit: int = 80,
        before_runtime_message_id: int | None = None,
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: direct local message-store read.
        async with self.runtime.session_factory() as session:
            message_repository = MessageRepository(session)
            chat = await self._require_local_chat(
                session,
                chat_id,
                runtime_only_message=(
                    "Локальная message history для этого чата ещё не собрана. "
                    "Сначала подтяни чат через sync."
                ),
            )

            if before_runtime_message_id is None:
                recent_desc = await message_repository.get_recent_messages(
                    chat_id=chat.id,
                    limit=max(1, limit),
                )
            else:
                recent_desc = await message_repository.get_recent_messages_before(
                    chat_id=chat.id,
                    before_telegram_message_id=before_runtime_message_id,
                    limit=max(1, limit),
                )
            messages = list(reversed(recent_desc))
            serialized_messages = [
                serialize_message(
                    message,
                    session_file=self.settings.fullaccess_session_file,
                    telegram_chat_id=chat.telegram_chat_id,
                )
                for message in messages
            ]
            return {
                "chat": serialize_chat(
                    chat,
                    message_count=await message_repository.count_messages_for_chat(chat_id=chat.id),
                    last_message=recent_desc[0] if recent_desc else None,
                    session_file=self.settings.fullaccess_session_file,
                    asset_session_files=self._asset_session_files(),
                ),
                "messages": serialized_messages,
                "history": {
                    "limit": max(1, limit),
                    "returnedCount": len(serialized_messages),
                    "hasMoreBefore": bool(
                        serialized_messages
                        and serialized_messages[0].get("runtimeMessageId")
                        and int(serialized_messages[0]["runtimeMessageId"]) > 1
                    ),
                    "beforeRuntimeMessageId": (
                        int(serialized_messages[0]["runtimeMessageId"])
                        if serialized_messages and serialized_messages[0].get("runtimeMessageId") is not None
                        else None
                    ),
                    "oldestMessageKey": serialized_messages[0].get("messageKey") if serialized_messages else None,
                    "newestMessageKey": serialized_messages[-1].get("messageKey") if serialized_messages else None,
                    "oldestRuntimeMessageId": (
                        int(serialized_messages[0]["runtimeMessageId"])
                        if serialized_messages and serialized_messages[0].get("runtimeMessageId") is not None
                        else None
                    ),
                    "newestRuntimeMessageId": (
                        int(serialized_messages[-1]["runtimeMessageId"])
                        if serialized_messages and serialized_messages[-1].get("runtimeMessageId") is not None
                        else None
                    ),
                },
                "refreshedAt": serialize_datetime(datetime.now(timezone.utc)),
            }

    async def get_reply_preview(
        self,
        chat_id: int,
        *,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        route = self._runtime_manager.route_status("replyGeneration")
        try:
            return await self._runtime_manager.surface("replyGeneration").get_reply_preview(
                chat_id,
                use_provider_refinement=use_provider_refinement,
            )
        except RuntimeUnavailableError:
            raise
        except Exception as error:
            if route.requested == "new":
                raise RuntimeUnavailableError(
                    str(error),
                    code="degraded",
                    action_hint="Повтори сборку reply через новый runtime.",
                ) from error
            raise

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
            return decorate_reply_payload(
                serialize_reply_result(result),
                send_enabled=False,
            )

    async def send_chat_message(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        reply_to_source_message_id: int | None = None,
        source_message_key: str | None = None,
        reply_to_source_message_key: str | None = None,
        draft_scope_key: str | None = None,
        client_send_id: str | None = None,
    ) -> dict[str, Any]:
        cleaned_text = text.strip()
        route = self._runtime_manager.route_status("sendPath")
        route_payload = route.to_payload()
        target = await self._resolve_manual_send_target(
            chat_id,
            source_message_key=source_message_key or reply_to_source_message_key,
        )
        availability = await self._build_manual_send_availability(
            target=target,
            route_payload=route_payload,
        )
        backend = str(availability["effectiveBackend"])
        source = _resolve_runtime_surface_source(
            requested=str(route_payload.get("requested")),
            effective=backend,
        )
        fallback_used = bool(availability.get("fallbackUsed"))
        fallback_reason = availability.get("fallbackReason")
        guard_key = _build_manual_send_guard_key(
            target=target,
            text=cleaned_text,
            source_message_id=source_message_id,
            source_message_key=source_message_key,
            draft_scope_key=draft_scope_key,
            client_send_id=client_send_id,
        )

        if not cleaned_text:
            return await self._build_and_record_manual_send_response(
                ok=False,
                status="failed",
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=text,
                reason="Нельзя отправить пустое сообщение.",
                error={"code": "empty_text", "message": "Нельзя отправить пустое сообщение."},
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        if not availability["available"]:
            reason = str(availability.get("reason") or "Отправка сейчас недоступна.")
            return await self._build_and_record_manual_send_response(
                ok=False,
                status="unavailable",
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=text,
                reason=reason,
                error={"code": str(availability.get("code") or "send_unavailable"), "message": reason},
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        duplicate_reason = self._manual_send_duplicate_reason(guard_key)
        if duplicate_reason is not None:
            return await self._build_and_record_manual_send_response(
                ok=False,
                status="failed",
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=text,
                reason=duplicate_reason,
                error={"code": "duplicate_send", "message": duplicate_reason},
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )

        self._manual_send_inflight.add(guard_key)
        try:
            send_payload = await self._runtime_manager.surface("sendPath").send_chat_message(
                chat_id,
                text=cleaned_text,
                source_message_id=source_message_id,
                reply_to_source_message_id=reply_to_source_message_id,
                source_message_key=source_message_key,
                reply_to_source_message_key=reply_to_source_message_key,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
            )
            workspace = await self.get_chat_workspace(chat_id, limit=80, execute_reply_modes=False)
            sent_message = send_payload.get("sentMessage") if isinstance(send_payload.get("sentMessage"), dict) else None
            sent_identity = _build_sent_message_identity(sent_message, send_payload)
            self._manual_send_recent_success_at[guard_key] = datetime.now(timezone.utc)
            status = "degraded" if fallback_used else "success"
            return await self._build_and_record_manual_send_response(
                ok=True,
                status=status,
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=cleaned_text,
                reason=(
                    str(fallback_reason)
                    if fallback_used and fallback_reason is not None
                    else "Сообщение отправлено."
                ),
                sent_message=sent_message,
                sent_message_identity=sent_identity,
                workspace=workspace,
                trace=send_payload.get("trace") if isinstance(send_payload.get("trace"), dict) else None,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
        except RuntimeUnavailableError as error:
            return await self._build_and_record_manual_send_response(
                ok=False,
                status="unavailable",
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=cleaned_text,
                reason=str(error),
                error={"code": "runtime_unavailable", "message": str(error)},
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
        except LookupError as error:
            return await self._build_and_record_manual_send_response(
                ok=False,
                status="unavailable",
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=cleaned_text,
                reason=str(error),
                error={"code": "chat_unavailable", "message": str(error)},
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
        except ValueError as error:
            return await self._build_and_record_manual_send_response(
                ok=False,
                status="failed",
                route=route_payload,
                source=source,
                effective_backend=backend,
                target=target,
                draft_scope_key=draft_scope_key,
                client_send_id=client_send_id,
                text=cleaned_text,
                reason=str(error),
                error={"code": "send_failed", "message": str(error)},
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
        finally:
            self._manual_send_inflight.discard(guard_key)

    async def prepare_chat_send(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        source_message_key: str | None = None,
        draft_scope_key: str | None = None,
        client_send_id: str | None = None,
    ) -> dict[str, Any]:
        cleaned_text = text.strip()
        route = self._runtime_manager.route_status("sendPath").to_payload()
        target = await self._resolve_manual_send_target(
            chat_id,
            source_message_key=source_message_key,
        )
        availability = await self._build_manual_send_availability(
            target=target,
            route_payload=route,
        )
        backend = str(availability["effectiveBackend"])
        source = _resolve_runtime_surface_source(
            requested=str(route.get("requested")),
            effective=backend,
        )
        guard_key = _build_manual_send_guard_key(
            target=target,
            text=cleaned_text,
            source_message_id=source_message_id,
            source_message_key=source_message_key,
            draft_scope_key=draft_scope_key,
            client_send_id=client_send_id,
        )
        duplicate_reason = self._manual_send_duplicate_reason(guard_key) if cleaned_text else None
        ready = bool(cleaned_text and availability["available"] and duplicate_reason is None)
        reason = (
            None
            if ready
            else "Нельзя отправить пустое сообщение."
            if not cleaned_text
            else duplicate_reason
            if duplicate_reason is not None
            else str(availability.get("reason") or "Отправка сейчас недоступна.")
        )
        return {
            "ok": ready,
            "status": "success" if ready else "unavailable",
            "ready": ready,
            "reason": reason,
            "error": None if ready else {"code": str(availability.get("code") or "send_unavailable"), "message": reason},
            "source": source,
            "requestedBackend": route.get("requested"),
            "effectiveBackend": backend,
            "backend": backend,
            "route": route,
            "target": _manual_send_target_payload(target),
            "fallback": {
                "used": bool(availability.get("fallbackUsed")),
                "reason": availability.get("fallbackReason"),
            },
            "draft": {
                "scopeKey": draft_scope_key,
                "sourceMessageId": source_message_id,
                "sourceMessageKey": source_message_key,
                "textLength": len(cleaned_text),
            },
            "debug": {
                "clientSendId": client_send_id,
                "duplicateGuardKey": guard_key,
            },
        }

    async def _legacy_send_chat_message(
        self,
        chat_id: int,
        *,
        text: str,
        source_message_id: int | None = None,
        reply_to_source_message_id: int | None = None,
        source_message_key: str | None = None,
        reply_to_source_message_key: str | None = None,
        draft_scope_key: str | None = None,
        client_send_id: str | None = None,
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

    async def _resolve_manual_send_target(
        self,
        chat_id: int,
        *,
        source_message_key: str | None = None,
    ) -> ManualSendTarget:
        async with self.runtime.session_factory() as session:
            chat_repository = ChatRepository(session)
            if int(chat_id) > 0:
                chat = await chat_repository.get_by_id(int(chat_id))
                if chat is None:
                    return ManualSendTarget(
                        requested_chat_id=int(chat_id),
                        local_chat_id=None,
                        runtime_chat_id=None,
                    )
                return ManualSendTarget(
                    requested_chat_id=int(chat_id),
                    local_chat_id=chat.id,
                    runtime_chat_id=chat.telegram_chat_id,
                )

            runtime_chat_id = _runtime_chat_id_from_message_key(source_message_key)
            if runtime_chat_id is None:
                runtime_chat_id = parse_runtime_only_chat_id(int(chat_id))
            if runtime_chat_id is None:
                return ManualSendTarget(
                    requested_chat_id=int(chat_id),
                    local_chat_id=None,
                    runtime_chat_id=None,
                )
            local_chat = await chat_repository.get_by_telegram_chat_id(runtime_chat_id)
            return ManualSendTarget(
                requested_chat_id=int(chat_id),
                local_chat_id=local_chat.id if local_chat is not None else None,
                runtime_chat_id=runtime_chat_id,
            )

    async def _build_manual_send_availability(
        self,
        *,
        target: ManualSendTarget,
        route_payload: dict[str, Any],
    ) -> dict[str, Any]:
        effective = str(route_payload.get("effective") or "legacy")
        route_status = str(route_payload.get("status") or "available")
        route_reason = route_payload.get("reason") if isinstance(route_payload.get("reason"), str) else None

        if target.runtime_chat_id is None:
            return {
                "available": False,
                "code": "unknown_chat",
                "reason": "Чат не найден или недоступен для отправки.",
                "effectiveBackend": effective,
                "fallbackUsed": False,
                "fallbackReason": None,
            }

        if route_status != "available":
            return {
                "available": False,
                "code": str(route_payload.get("reasonCode") or "send_unavailable"),
                "reason": route_reason or "Отправка через выбранный runtime сейчас недоступна.",
                "effectiveBackend": effective,
                "fallbackUsed": False,
                "fallbackReason": None,
            }

        if effective == "new":
            return {
                "available": True,
                "code": None,
                "reason": None,
                "effectiveBackend": "new",
                "fallbackUsed": False,
                "fallbackReason": None,
            }

        if target.local_chat_id is None:
            return {
                "available": False,
                "code": "runtime_only_legacy_unavailable",
                "reason": "Legacy send-path требует локальный чат; runtime-only чат доступен только через new runtime.",
                "effectiveBackend": "legacy",
                "fallbackUsed": False,
                "fallbackReason": None,
            }

        async with self.runtime.session_factory() as session:
            status = await self._build_fullaccess_auth_service(session).build_status_report()
        return {
            "available": bool(status.ready_for_manual_send),
            "code": None if status.ready_for_manual_send else "legacy_write_unavailable",
            "reason": None if status.ready_for_manual_send else status.reason,
            "effectiveBackend": "legacy",
            "fallbackUsed": False,
            "fallbackReason": None,
        }

    def _manual_send_duplicate_reason(self, guard_key: str) -> str | None:
        if guard_key in self._manual_send_inflight:
            return "Похожая отправка уже выполняется. Повторный клик заблокирован."
        recent_success_at = self._manual_send_recent_success_at.get(guard_key)
        if recent_success_at is None:
            return None
        age_seconds = (datetime.now(timezone.utc) - recent_success_at).total_seconds()
        if age_seconds <= MANUAL_SEND_DUPLICATE_WINDOW_SECONDS:
            return "Похожее сообщение уже только что отправлено. Повторная отправка заблокирована."
        return None

    async def _build_and_record_manual_send_response(
        self,
        *,
        ok: bool,
        status: str,
        route: dict[str, Any],
        source: str,
        effective_backend: str,
        target: ManualSendTarget,
        draft_scope_key: str | None,
        client_send_id: str | None,
        text: str,
        reason: str | None,
        error: dict[str, Any] | None = None,
        sent_message: dict[str, Any] | None = None,
        sent_message_identity: dict[str, Any] | None = None,
        workspace: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
        fallback_used: bool = False,
        fallback_reason: Any = None,
    ) -> dict[str, Any]:
        timestamp = serialize_datetime(datetime.now(timezone.utc))
        journal_payload = {
            "timestamp": timestamp,
            "chatKey": target.chat_key,
            "runtimeChatId": target.runtime_chat_id,
            "localChatId": target.local_chat_id,
            "requestedChatId": target.requested_chat_id,
            "backend": effective_backend,
            "requestedBackend": route.get("requested"),
            "effectiveBackend": effective_backend,
            "draftScopeKey": draft_scope_key,
            "clientSendId": client_send_id,
            "success": ok,
            "status": status,
            "reason": reason,
            "errorReason": error.get("message") if isinstance(error, dict) else None,
            "errorCode": error.get("code") if isinstance(error, dict) else None,
            "sentMessageIdentity": sent_message_identity,
            "route": route,
            "fallback": {
                "used": fallback_used,
                "reason": fallback_reason,
            },
        }
        await self._record_manual_send_journal(
            target=target,
            payload=journal_payload,
            text=text,
        )
        if ok:
            log_event(
                LOGGER,
                20,
                "desktop.manual_send.completed",
                "Ручная отправка из Desktop завершена.",
                chat_key=target.chat_key,
                runtime_chat_id=target.runtime_chat_id,
                local_chat_id=target.local_chat_id,
                backend=effective_backend,
                draft_scope_key=draft_scope_key,
                sent_message_identity=sent_message_identity,
            )
        else:
            log_event(
                LOGGER,
                30,
                "desktop.manual_send.failed",
                "Ручная отправка из Desktop не выполнена.",
                chat_key=target.chat_key,
                runtime_chat_id=target.runtime_chat_id,
                local_chat_id=target.local_chat_id,
                backend=effective_backend,
                draft_scope_key=draft_scope_key,
                reason=reason,
                error=error,
            )
        return {
            "ok": ok,
            "status": status,
            "reason": reason,
            "error": error,
            "source": source,
            "requestedBackend": route.get("requested"),
            "effectiveBackend": effective_backend,
            "backend": effective_backend,
            "route": route,
            "fallback": {
                "used": fallback_used,
                "reason": fallback_reason,
            },
            "target": _manual_send_target_payload(target),
            "sentMessage": sent_message,
            "sentMessageIdentity": sent_message_identity,
            "workspace": workspace,
            "debug": {
                "journal": journal_payload,
                "trace": trace,
            },
        }

    async def _record_manual_send_journal(
        self,
        *,
        target: ManualSendTarget,
        payload: dict[str, Any],
        text: str,
    ) -> None:
        async with self.runtime.session_factory() as session:
            setting_repository = SettingRepository(session)
            await OperationalStateService(setting_repository).record_manual_send(
                payload=payload,
            )
            await WorkflowJournalService(setting_repository).append_chat_event(
                target.local_chat_id or target.requested_chat_id,
                build_workflow_event(
                    action="manual_send",
                    mode="desktop",
                    status=str(payload.get("status") or "unknown"),
                    actor="desktop",
                    automatic=False,
                    message="Ручная отправка из Desktop",
                    reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
                    trigger="desktop_manual",
                    chat_id=target.local_chat_id or target.requested_chat_id,
                    sent_message_id=_pick_local_message_id(payload.get("sentMessageIdentity")),
                    text_preview=_preview_text(text),
                    chat_key=target.chat_key,
                    runtime_chat_id=target.runtime_chat_id,
                    backend=payload.get("backend") if isinstance(payload.get("backend"), str) else None,
                    draft_scope_key=payload.get("draftScopeKey") if isinstance(payload.get("draftScopeKey"), str) else None,
                    sent_message_key=_pick_message_key(payload.get("sentMessageIdentity")),
                    error_code=payload.get("errorCode") if isinstance(payload.get("errorCode"), str) else None,
                ),
            )
            await session.commit()

    async def update_autopilot_global(
        self,
        *,
        mode: str | None = None,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
        emergency_stop: bool | None = None,
        autopilot_paused: bool | None = None,
    ) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            policy = await service.update_global_policy(
                mode=mode,
                master_enabled=master_enabled,
                allow_channels=allow_channels,
                emergency_stop=emergency_stop,
                autopilot_paused=autopilot_paused,
            )
            payload = await service.get_status_payload()
            await OperationalStateService(SettingRepository(session)).record_reply_execution(payload=payload)
            await session.commit()
            return {
                **payload,
                "settings": {
                    "master_enabled": policy.master_enabled,
                    "allow_channels": policy.allow_channels,
                    "cooldown_seconds": policy.cooldown_seconds,
                    "min_prepare_confidence": policy.min_prepare_confidence,
                    "min_send_confidence": policy.min_send_confidence,
                },
            }

    async def _legacy_update_autopilot_global(
        self,
        *,
        mode: str | None = None,
        master_enabled: bool | None = None,
        allow_channels: bool | None = None,
        emergency_stop: bool | None = None,
        autopilot_paused: bool | None = None,
    ) -> dict[str, Any]:
        # LEGACY_RUNTIME: settings-only autopilot control surface.
        async with self.runtime.session_factory() as session:
            payload = await self._build_autopilot_service(session).update_global_settings(
                master_enabled=master_enabled if master_enabled is not None else (normalize_reply_execution_mode(mode) != "off" if mode is not None else None),
                allow_channels=allow_channels,
            )
            await session.commit()
            return {"settings": payload}

    async def update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        allowed: bool | None = None,
        autopilot_allowed: bool | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        workspace = await self.get_chat_workspace(chat_id, limit=60, execute_reply_modes=False)
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            await service.update_chat_policy(
                requested_chat_id=chat_id,
                chat_payload=workspace.get("chat") if isinstance(workspace.get("chat"), dict) else None,
                trusted=trusted,
                allowed=allowed,
                autopilot_allowed=autopilot_allowed,
                mode=mode,
            )
            await session.commit()

        refreshed = await self.get_chat_workspace(chat_id, limit=60, execute_reply_modes=False)
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            status = await service.get_status_payload(
                requested_chat_id=chat_id,
                chat_payload=refreshed.get("chat") if isinstance(refreshed.get("chat"), dict) else None,
            )
            await OperationalStateService(SettingRepository(session)).record_reply_execution(payload=status)
            await session.commit()
        autopilot = status.get("autopilot") if isinstance(status.get("autopilot"), dict) else None
        if autopilot is not None:
            refreshed["autopilot"] = autopilot
        return {
            "chat": refreshed.get("chat"),
            "policy": status.get("chatPolicy"),
            "autopilot": refreshed.get("autopilot"),
            "workspace": refreshed,
        }

    async def _legacy_update_chat_autopilot(
        self,
        chat_id: int,
        *,
        trusted: bool | None = None,
        allowed: bool | None = None,
        autopilot_allowed: bool | None = None,
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
                    asset_session_files=self._asset_session_files(),
                ),
                "autopilot": overview,
            }

    async def get_autopilot_status(self, *, chat_id: int | None = None) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        chat_payload: dict[str, Any] | None = None
        if chat_id is not None:
            workspace = await self.get_chat_workspace(chat_id, limit=60, execute_reply_modes=False)
            chat_payload = workspace.get("chat") if isinstance(workspace.get("chat"), dict) else None
        async with self.runtime.session_factory() as session:
            payload = await self._build_reply_execution_service(session).get_status_payload(
                requested_chat_id=chat_id,
                chat_payload=chat_payload,
            )
            return payload

    async def emergency_stop_autopilot(self) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            await service.emergency_stop()
            payload = await service.get_status_payload()
            await OperationalStateService(SettingRepository(session)).record_reply_execution(payload=payload)
            await session.commit()
            return payload

    async def pause_autopilot(self, *, paused: bool = True) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            await service.pause_autopilot(paused=paused)
            payload = await service.get_status_payload()
            await OperationalStateService(SettingRepository(session)).record_reply_execution(payload=payload)
            await session.commit()
            return payload

    async def list_autopilot_activity(self, *, limit: int = 20) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        async with self.runtime.session_factory() as session:
            events = await WorkflowJournalService(SettingRepository(session)).list_global_events(limit=limit)
            return {"items": list(events), "count": len(events)}

    async def confirm_autopilot_pending(
        self,
        chat_id: int,
        *,
        pending_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_autopilot_control_available()
        workspace = await self.get_chat_workspace(chat_id, limit=60, execute_reply_modes=False)
        chat_payload = workspace.get("chat") if isinstance(workspace.get("chat"), dict) else None
        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            try:
                chat_policy, state, pending = await service.prepare_confirm_send(
                    requested_chat_id=chat_id,
                    chat_payload=chat_payload,
                    pending_id=pending_id,
                )
            except ReplyExecutionActionError as error:
                await session.commit()
                return {
                    "ok": False,
                    "status": "blocked",
                    "reason": str(error),
                    "error": {"code": error.code, "message": str(error)},
                    "autopilot": error.autopilot,
                    "workspace": None,
                }
            await session.commit()

        try:
            send_payload = await self._send_reply_execution_via_new_send_path(chat_id, pending=pending)
        except Exception as error:
            async with self.runtime.session_factory() as session:
                service = self._build_reply_execution_service(session)
                state = await service.mark_failed(
                    chat_policy=chat_policy,
                    state=state,
                    pending=pending,
                    error=str(error),
                    actor="desktop",
                    automatic=False,
                )
                autopilot = await service._build_autopilot_payload(
                    global_policy=await service.get_global_policy(),
                    chat_policy=chat_policy,
                    state=state,
                    decision=service.machine._decision(
                        mode=chat_policy.mode,
                        effective_mode=chat_policy.mode,
                        status="failed",
                        action="send",
                        allowed=False,
                        reason_code="send_failed",
                        confidence=None,
                        trigger=None,
                        focus=None,
                        opportunity=None,
                        source_message_id=None,
                        source_message_key=None,
                        source_runtime_message_id=None,
                        reply_text=None,
                        draft_scope_key=None,
                        execution_id=None,
                        execution_key=None,
                    ),
                )
                await session.commit()
            return {
                "ok": False,
                "status": "failed",
                "reason": str(error),
                "error": {"code": "send_failed", "message": str(error)},
                "autopilot": autopilot,
                "workspace": None,
            }

        async with self.runtime.session_factory() as session:
            service = self._build_reply_execution_service(session)
            state = await service.mark_sent(
                chat_policy=chat_policy,
                state=state,
                pending=pending,
                sent_payload=send_payload,
                actor="desktop",
                automatic=False,
            )
            autopilot = await service._build_autopilot_payload(
                global_policy=await service.get_global_policy(),
                chat_policy=chat_policy,
                state=state,
                decision=service.machine._decision(
                    mode=chat_policy.mode,
                    effective_mode=chat_policy.mode,
                    status="sent",
                    action="send",
                    allowed=True,
                    reason_code="sent",
                    confidence=None,
                    trigger=None,
                    focus=None,
                    opportunity=None,
                    source_message_id=None,
                    source_message_key=None,
                    source_runtime_message_id=None,
                    reply_text=None,
                    draft_scope_key=None,
                    execution_id=None,
                    execution_key=None,
                ),
            )
            await session.commit()
        workspace = await self.get_chat_workspace(chat_id, limit=80, execute_reply_modes=False)
        workspace["autopilot"] = autopilot
        return {
            "ok": True,
            "status": "sent",
            "reason": "Сообщение отправлено после явного confirm.",
            "error": None,
            "autopilot": autopilot,
            "sentMessage": send_payload.get("sentMessage") if isinstance(send_payload, dict) else None,
            "sentMessageIdentity": send_payload.get("sentMessageIdentity") if isinstance(send_payload, dict) else None,
            "workspace": workspace,
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
                    asset_session_files=self._asset_session_files(),
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
                    asset_session_files=self._asset_session_files(),
                ),
            }

    async def sync_source(self, chat_id: int) -> dict[str, Any]:
        async with self.runtime.session_factory() as session:
            resolved = await self._resolve_chat_handle(session, chat_id)
            if resolved.local_chat_id is not None:
                chat = await ChatRepository(session).get_by_id(resolved.local_chat_id)
                if chat is None:
                    raise LookupError("Источник не найден.")
                reference = build_chat_reference(chat)
            elif resolved.runtime_chat_id is not None:
                reference = str(resolved.runtime_chat_id)
            else:
                raise LookupError("Источник не найден.")

            result = await self._build_fullaccess_sync_service(session).sync_chat(reference)
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

    def _build_reply_execution_service(self, session) -> ReplyExecutionService:
        setting_repository = SettingRepository(session)
        return ReplyExecutionService(
            chat_repository=ChatRepository(session),
            setting_repository=setting_repository,
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
        return build_reply_service(self.settings, session)

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
        serialized_messages = [
            serialize_message(
                message,
                session_file=self.settings.fullaccess_session_file,
                telegram_chat_id=chat.telegram_chat_id,
            )
            for message in messages
        ]
        reply_payload = decorate_reply_payload(
            serialize_reply_result(reply_result),
            send_enabled=False,
        )
        reply_context = build_reply_context_payload(
            reply_payload=reply_payload,
            message_payloads=serialized_messages,
            source_backend="legacy",
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
        serialized_chat = serialize_chat(
            chat,
            message_count=message_count,
            last_message=last_message,
            session_file=self.settings.fullaccess_session_file,
            asset_session_files=self._asset_session_files(),
        )
        return {
            "chat": serialized_chat,
            "messages": serialized_messages,
            "history": self._build_history_payload_from_messages(serialized_messages, limit=limit),
            "replyContext": reply_context,
            "reply": reply_payload,
            "autopilot": autopilot,
            "freshness": freshness,
            "status": {
                "source": "legacy",
                "effectiveBackend": "legacy",
                "degraded": False,
                "degradedReason": None,
                "syncTrigger": freshness.get("syncTrigger"),
                "updatedNow": freshness.get("updatedNow"),
                "syncError": freshness.get("syncError"),
                "lastUpdatedAt": serialize_datetime(datetime.now(timezone.utc)),
                "lastSuccessAt": None,
                "lastError": None,
                "lastErrorAt": None,
                "availability": {
                    "workspaceAvailable": True,
                    "historyReadable": True,
                    "runtimeReadable": False,
                    "legacyWorkspaceAvailable": True,
                    "replyContextAvailable": bool(reply_context.get("available")),
                    "sendAvailable": fullaccess_status.ready_for_manual_send,
                    "autopilotAvailable": autopilot is not None,
                    "canLoadOlder": bool(serialized_messages and serialized_messages[0].get("runtimeMessageId") and int(serialized_messages[0]["runtimeMessageId"]) > 1),
                },
                "messageSource": {
                    "backend": "legacy_local_store",
                    "chatKey": serialized_chat.get("chatKey"),
                    "runtimeChatId": chat.telegram_chat_id,
                    "localChatId": chat.id,
                    "oldestMessageKey": serialized_messages[0].get("messageKey") if serialized_messages else None,
                    "newestMessageKey": serialized_messages[-1].get("messageKey") if serialized_messages else None,
                    "oldestRuntimeMessageId": (
                        serialized_messages[0].get("runtimeMessageId") if serialized_messages else None
                    ),
                    "newestRuntimeMessageId": (
                        serialized_messages[-1].get("runtimeMessageId") if serialized_messages else None
                    ),
                },
            },
            "refreshedAt": serialize_datetime(datetime.now(timezone.utc)),
        }

    def _build_reply_context_payload(
        self,
        *,
        reply_payload: dict[str, Any],
        message_payloads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return build_reply_context_payload(
            reply_payload=reply_payload,
            message_payloads=message_payloads,
            source_backend="legacy",
        )

    def _build_history_payload_from_messages(
        self,
        message_payloads: list[dict[str, Any]],
        *,
        limit: int,
    ) -> dict[str, Any]:
        oldest = message_payloads[0] if message_payloads else None
        newest = message_payloads[-1] if message_payloads else None
        return {
            "limit": max(1, limit),
            "returnedCount": len(message_payloads),
            "hasMoreBefore": bool(
                oldest is not None
                and oldest.get("runtimeMessageId") is not None
                and int(oldest["runtimeMessageId"]) > 1
            ),
            "beforeRuntimeMessageId": (
                int(oldest["runtimeMessageId"])
                if oldest is not None and oldest.get("runtimeMessageId") is not None
                else None
            ),
            "oldestMessageKey": oldest.get("messageKey") if oldest is not None else None,
            "newestMessageKey": newest.get("messageKey") if newest is not None else None,
            "oldestRuntimeMessageId": (
                int(oldest["runtimeMessageId"])
                if oldest is not None and oldest.get("runtimeMessageId") is not None
                else None
            ),
            "newestRuntimeMessageId": (
                int(newest["runtimeMessageId"])
                if newest is not None and newest.get("runtimeMessageId") is not None
                else None
            ),
        }

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
        new_runtime_auth = (
            new_runtime_payload.get("auth")
            if isinstance(new_runtime_payload.get("auth"), dict)
            else {}
        )
        runtime_active = bool(new_runtime_payload.get("active"))
        runtime_auth_state = str(new_runtime_auth.get("state") or "idle")
        runtime_account = (
            cast(dict[str, Any], new_runtime_auth.get("user")).get("username")
            if isinstance(new_runtime_auth.get("user"), dict)
            else None
        )
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
                "status": (
                    "online"
                    if runtime_auth_state == "authorized"
                    else "warning"
                    if runtime_active or runtime_auth_state in {"awaiting_code", "awaiting_password", "error"}
                    else "muted"
                ),
                "value": (
                    "авторизован"
                    if runtime_auth_state == "authorized"
                    else "ждёт пароль"
                    if runtime_auth_state == "awaiting_password"
                    else "ждёт код"
                    if runtime_auth_state in {"code_requested", "awaiting_code"}
                    else "ошибка"
                    if runtime_auth_state == "error"
                    else "inactive"
                ),
                "detail": runtime_account or runtime_detail,
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

    async def _record_chat_roster_state(self, roster_state: dict[str, Any]) -> None:
        async with self.runtime.session_factory() as session:
            await OperationalStateService(SettingRepository(session)).record_chat_roster_status(
                payload=roster_state,
            )
            await session.commit()

    async def _get_chat_roster_state(self) -> dict[str, Any] | None:
        async with self.runtime.session_factory() as session:
            event = await OperationalStateService(SettingRepository(session)).get_chat_roster_status()
        route = self._runtime_manager.route_status("chatRoster").to_payload()
        if event is None:
            if route.get("status") != "available":
                return self._build_chat_roster_state(
                    route=route,
                    source=_resolve_runtime_surface_source(
                        requested=str(route.get("requested") or "legacy"),
                        effective=str(route.get("effective") or "legacy"),
                    ),
                    effective_backend=str(route.get("effective") or route.get("requested") or "legacy"),
                    refreshed_at=None,
                    runtime_meta={},
                    last_error=route.get("reason") if isinstance(route.get("reason"), str) else None,
                )
            return None
        payload = event.payload.get("payload")
        if not isinstance(payload, dict):
            return None
        if route.get("status") != "available":
            return self._build_chat_roster_state(
                route=route,
                source=_resolve_runtime_surface_source(
                    requested=str(route.get("requested") or "legacy"),
                    effective=str(route.get("effective") or "legacy"),
                ),
                effective_backend=str(route.get("effective") or route.get("requested") or "legacy"),
                refreshed_at=payload.get("lastUpdatedAt"),
                runtime_meta={},
                last_error=route.get("reason") if isinstance(route.get("reason"), str) else None,
            )
        return payload

    async def _record_message_workspace_state(self, workspace_state: dict[str, Any]) -> None:
        async with self.runtime.session_factory() as session:
            await OperationalStateService(SettingRepository(session)).record_message_workspace_status(
                payload=workspace_state,
            )
            await session.commit()

    async def _get_message_workspace_state(self) -> dict[str, Any] | None:
        async with self.runtime.session_factory() as session:
            event = await OperationalStateService(SettingRepository(session)).get_message_workspace_status()
        route = self._runtime_manager.route_status("messageWorkspace").to_payload()
        if event is None:
            if route.get("status") != "available":
                return _build_unavailable_workspace_status(route=route)
            return None
        payload = event.payload.get("payload")
        if not isinstance(payload, dict):
            return None
        if route.get("status") != "available":
            return _build_unavailable_workspace_status(
                route=route,
                last_updated_at=payload.get("lastUpdatedAt") if isinstance(payload.get("lastUpdatedAt"), str) else None,
            )
        return payload

    async def _get_manual_send_state(self) -> dict[str, Any] | None:
        async with self.runtime.session_factory() as session:
            event = await OperationalStateService(SettingRepository(session)).get_manual_send_status()
        if event is None:
            return None
        payload = event.payload.get("payload")
        return payload if isinstance(payload, dict) else None

    async def _get_live_status(self) -> dict[str, Any] | None:
        async with self.runtime.session_factory() as session:
            service = OperationalStateService(SettingRepository(session))
            event = await service.get_live_status()
            recent = await service.list_live_activity(limit=8)
        payload = event.payload.get("payload") if event is not None else None
        if not isinstance(payload, dict):
            payload = {}
        payload["activity"] = list(recent)
        return payload

    async def _record_live_result(
        self,
        result: LiveRefreshResult,
        *,
        chat_id: int | None = None,
    ) -> None:
        await self._record_live_event(result.event, chat_id=chat_id)

    async def _record_live_event(
        self,
        event: dict[str, Any],
        *,
        chat_id: int | None = None,
    ) -> None:
        if not bool(event.get("record")) and event.get("reasonCode") == "interval_not_due":
            return
        async with self.runtime.session_factory() as session:
            setting_repository = SettingRepository(session)
            operational_state = OperationalStateService(setting_repository)
            await operational_state.record_live_status(payload=event)
            if bool(event.get("record")):
                await operational_state.record_live_activity(payload=event)
                if chat_id is not None and event.get("scope") == "active_chat":
                    await WorkflowJournalService(setting_repository).append_chat_event(
                        chat_id,
                        build_workflow_event(
                            action="live_refresh",
                            mode="live",
                            status=str(event.get("status") or "unknown"),
                            actor="desktop_live",
                            automatic=event.get("reason") not in {"manual_refresh", "control"},
                            message=_live_event_message(event),
                            reason=event.get("lastError") if isinstance(event.get("lastError"), str) else None,
                            reason_code=event.get("reasonCode") if isinstance(event.get("reasonCode"), str) else None,
                            trigger=event.get("reasonCode") if isinstance(event.get("reasonCode"), str) else None,
                            chat_id=chat_id,
                            chat_key=None,
                            runtime_chat_id=None,
                            backend=event.get("refreshSource") if isinstance(event.get("refreshSource"), str) else None,
                            error_code=(
                                event.get("reasonCode")
                                if event.get("status") == "degraded" and isinstance(event.get("reasonCode"), str)
                                else None
                            ),
                        ),
                    )
            await session.commit()

    def _build_chat_roster_state(
        self,
        *,
        route: dict[str, Any],
        source: str,
        effective_backend: str,
        refreshed_at: Any,
        runtime_meta: dict[str, Any],
        last_error: str | None,
    ) -> dict[str, Any]:
        route_reason = route.get("reason") if isinstance(route.get("reason"), str) else None
        degraded_reason = (
            last_error
            or route_reason
            or (
                runtime_meta.get("routeReason")
                if isinstance(runtime_meta.get("routeReason"), str)
                else None
            )
        )
        return {
            "source": source,
            "requestedBackend": route.get("requested"),
            "effectiveBackend": effective_backend,
            "degraded": bool(degraded_reason),
            "degradedReason": degraded_reason,
            "status": route.get("status") or ("degraded" if degraded_reason else "available"),
            "reasonCode": route.get("reasonCode"),
            "actionHint": route.get("actionHint"),
            "lastUpdatedAt": refreshed_at if isinstance(refreshed_at, str) or refreshed_at is None else serialize_datetime(refreshed_at),
            "lastSuccessAt": runtime_meta.get("lastSuccessAt"),
            "lastError": last_error or runtime_meta.get("lastError"),
            "lastErrorAt": runtime_meta.get("lastErrorAt"),
            "route": route,
        }

    def _decorate_workspace_status_payload(
        self,
        *,
        payload: dict[str, Any],
        route: dict[str, Any],
        source: str,
        effective_backend: str,
        last_error: str | None,
    ) -> dict[str, Any]:
        current_status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        runtime_meta = (
            current_status.get("runtimeMeta")
            if isinstance(current_status.get("runtimeMeta"), dict)
            else {}
        )
        availability = (
            current_status.get("availability")
            if isinstance(current_status.get("availability"), dict)
            else {}
        )
        message_source = (
            current_status.get("messageSource")
            if isinstance(current_status.get("messageSource"), dict)
            else {}
        )
        route_payload = dict(route)
        if effective_backend != route.get("effective"):
            route_payload["effective"] = effective_backend
            route_payload["reason"] = last_error or route.get("reason")

        route_reason = route_payload.get("reason") if isinstance(route_payload.get("reason"), str) else None
        send_route = self._runtime_manager.route_status("sendPath").to_payload()
        send_route_available = send_route.get("status") == "available"
        send_available = bool(availability.get("sendAvailable")) or (
            send_route_available and send_route.get("effective") == "new"
        )
        send_disabled_reason = _build_send_disabled_reason(
            send_available=send_available,
            send_route=send_route,
            current_disabled_reason=(
                current_status.get("sendDisabledReason")
                if isinstance(current_status.get("sendDisabledReason"), str)
                else None
            ),
        )
        degraded_reason = (
            last_error
            or (current_status.get("degradedReason") if isinstance(current_status.get("degradedReason"), str) else None)
            or route_reason
            or (runtime_meta.get("routeReason") if isinstance(runtime_meta.get("routeReason"), str) else None)
        )

        freshness = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
        status_payload = {
            "source": source,
            "requestedBackend": route_payload.get("requested"),
            "effectiveBackend": effective_backend,
            "degraded": (
                bool(degraded_reason)
                or bool(current_status.get("degraded"))
            ),
            "degradedReason": degraded_reason,
            "status": route_payload.get("status") or ("degraded" if degraded_reason else "available"),
            "reasonCode": route_payload.get("reasonCode"),
            "actionHint": route_payload.get("actionHint"),
            "syncTrigger": (
                freshness.get("syncTrigger")
                if isinstance(freshness.get("syncTrigger"), str)
                else current_status.get("syncTrigger")
            ),
            "updatedNow": bool(
                freshness.get("updatedNow")
                if "updatedNow" in freshness
                else current_status.get("updatedNow")
            ),
            "syncError": (
                freshness.get("syncError")
                if isinstance(freshness.get("syncError"), str)
                else last_error or current_status.get("syncError")
            ),
            "lastUpdatedAt": (
                payload.get("refreshedAt")
                if isinstance(payload.get("refreshedAt"), str) or payload.get("refreshedAt") is None
                else serialize_datetime(payload.get("refreshedAt"))
            ),
            "lastSuccessAt": runtime_meta.get("lastSuccessAt") or current_status.get("lastSuccessAt"),
            "lastError": last_error or current_status.get("lastError") or runtime_meta.get("lastError"),
            "lastErrorAt": current_status.get("lastErrorAt") or runtime_meta.get("lastErrorAt"),
            "availability": {
                "workspaceAvailable": bool(
                    availability.get("workspaceAvailable")
                    if "workspaceAvailable" in availability
                    else True
                ),
                "historyReadable": bool(
                    availability.get("historyReadable")
                    if "historyReadable" in availability
                    else True
                ),
                "runtimeReadable": bool(
                    availability.get("runtimeReadable")
                    if "runtimeReadable" in availability
                    else effective_backend == "new"
                ),
                "legacyWorkspaceAvailable": bool(
                    availability.get("legacyWorkspaceAvailable")
                    if "legacyWorkspaceAvailable" in availability
                    else effective_backend == "legacy"
                ),
                "replyContextAvailable": bool(availability.get("replyContextAvailable")),
                "sendAvailable": send_available,
                "autopilotAvailable": bool(availability.get("autopilotAvailable")),
                "canLoadOlder": bool(availability.get("canLoadOlder")),
            },
            "messageSource": {
                "backend": message_source.get("backend") or ("legacy_local_store" if effective_backend == "legacy" else "new_runtime"),
                "chatKey": message_source.get("chatKey"),
                "runtimeChatId": message_source.get("runtimeChatId"),
                "localChatId": message_source.get("localChatId"),
                "oldestMessageKey": message_source.get("oldestMessageKey"),
                "newestMessageKey": message_source.get("newestMessageKey"),
                "oldestRuntimeMessageId": message_source.get("oldestRuntimeMessageId"),
                "newestRuntimeMessageId": message_source.get("newestRuntimeMessageId"),
            },
            "route": route_payload,
            "sendPath": send_route,
            "sendDisabledReason": send_disabled_reason,
        }
        payload["status"] = status_payload
        _decorate_reply_send_actions(
            payload,
            send_available=send_available,
            disabled_reason=send_disabled_reason,
        )
        return status_payload

    async def _resolve_chat_handle(
        self,
        session,
        chat_id: int,
    ) -> ResolvedChatHandle:
        if chat_id > 0:
            return ResolvedChatHandle(
                requested_chat_id=chat_id,
                local_chat_id=chat_id,
                runtime_chat_id=None,
            )

        runtime_chat_id = parse_runtime_only_chat_id(chat_id)
        if runtime_chat_id is None:
            return ResolvedChatHandle(
                requested_chat_id=chat_id,
                local_chat_id=None,
                runtime_chat_id=None,
            )

        local_chat = await ChatRepository(session).get_by_telegram_chat_id(runtime_chat_id)
        return ResolvedChatHandle(
            requested_chat_id=chat_id,
            local_chat_id=local_chat.id if local_chat is not None else None,
            runtime_chat_id=runtime_chat_id,
        )

    async def _require_local_chat(
        self,
        session,
        chat_id: int,
        *,
        runtime_only_message: str,
    ):
        resolved = await self._resolve_chat_handle(session, chat_id)
        if resolved.local_chat_id is None:
            if resolved.runtime_chat_id is not None:
                raise LookupError(runtime_only_message)
            raise LookupError("Чат не найден.")

        chat = await ChatRepository(session).get_by_id(resolved.local_chat_id)
        if chat is None:
            raise LookupError("Чат не найден.")
        return chat

    def _asset_session_files(self) -> tuple[Path, ...]:
        return (
            self.settings.fullaccess_session_file,
            self.settings.runtime_new_session_file,
        )

    def _require_new_runtime_service(self) -> NewTelegramRuntimeService:
        if self._new_runtime_service is None:
            raise ValueError("Управление auth доступно только для встроенного managed new runtime.")
        return self._new_runtime_service

    def _ensure_autopilot_control_available(self) -> None:
        route = self._runtime_manager.route_status("autopilotControl")
        if route.status == "available":
            return
        raise RuntimeUnavailableError(
            route.reason or "Autopilot control недоступен через выбранный runtime.",
            code=route.reason_code,
            action_hint=route.action_hint,
        )


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


def _resolve_runtime_surface_source(*, requested: str, effective: str) -> str:
    if effective == "new":
        return "new"
    return "legacy"


def _build_unavailable_surface_status(
    *,
    route: dict[str, Any],
    reason: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    route_reason = route.get("reason") if isinstance(route.get("reason"), str) else None
    return {
        "available": False,
        "status": "unavailable",
        "reason": reason or route_reason or "Выбранный runtime surface сейчас недоступен.",
        "reasonCode": code or route.get("reasonCode") or "unavailable",
        "actionHint": route.get("actionHint"),
        "requestedBackend": route.get("requested"),
        "effectiveBackend": route.get("effective"),
        "route": route,
    }


def _build_unavailable_workspace_status(
    *,
    route: dict[str, Any],
    last_updated_at: str | None = None,
) -> dict[str, Any]:
    reason = route.get("reason") if isinstance(route.get("reason"), str) else "Workspace недоступен."
    effective_backend = str(route.get("effective") or route.get("requested") or "new")
    return {
        "source": _resolve_runtime_surface_source(
            requested=str(route.get("requested") or "legacy"),
            effective=effective_backend,
        ),
        "requestedBackend": route.get("requested"),
        "effectiveBackend": effective_backend,
        "degraded": True,
        "degradedReason": reason,
        "syncTrigger": None,
        "updatedNow": False,
        "syncError": reason,
        "lastUpdatedAt": last_updated_at,
        "lastSuccessAt": None,
        "lastError": reason,
        "lastErrorAt": None,
        "availability": {
            "workspaceAvailable": False,
            "historyReadable": False,
            "runtimeReadable": False,
            "legacyWorkspaceAvailable": False,
            "replyContextAvailable": False,
            "sendAvailable": False,
            "autopilotAvailable": False,
            "canLoadOlder": False,
        },
        "messageSource": {
            "backend": "unavailable",
            "chatKey": None,
            "runtimeChatId": None,
            "localChatId": None,
            "oldestMessageKey": None,
            "newestMessageKey": None,
            "oldestRuntimeMessageId": None,
            "newestRuntimeMessageId": None,
        },
        "route": route,
        "sendPath": route,
        "sendDisabledReason": "Отправка недоступна: workspace не читается новым runtime.",
    }


def _manual_send_target_payload(target: ManualSendTarget) -> dict[str, Any]:
    return {
        "requestedChatId": target.requested_chat_id,
        "localChatId": target.local_chat_id,
        "runtimeChatId": target.runtime_chat_id,
        "chatKey": target.chat_key,
    }


def _runtime_chat_id_from_message_key(message_key: str | None) -> int | None:
    parsed = parse_message_key(message_key)
    if parsed is None:
        return None
    return parsed[0]


def _build_manual_send_guard_key(
    *,
    target: ManualSendTarget,
    text: str,
    source_message_id: int | None,
    source_message_key: str | None,
    draft_scope_key: str | None,
    client_send_id: str | None,
) -> str:
    normalized_text = " ".join(text.split()).casefold()
    return "::".join(
        [
            str(target.chat_key or target.requested_chat_id),
            str(draft_scope_key or "no-draft-scope"),
            str(source_message_key or source_message_id or "no-source"),
            normalized_text,
        ]
    )


def _build_sent_message_identity(
    sent_message: dict[str, Any] | None,
    send_payload: dict[str, Any],
) -> dict[str, Any] | None:
    payload_identity = send_payload.get("sentMessageIdentity")
    if isinstance(payload_identity, dict):
        return payload_identity
    if sent_message is None:
        return None
    return {
        "chatKey": sent_message.get("chatKey"),
        "messageKey": sent_message.get("messageKey"),
        "runtimeChatId": None,
        "runtimeMessageId": sent_message.get("runtimeMessageId"),
        "localChatId": None,
        "localMessageId": sent_message.get("localMessageId"),
    }


def _pick_local_message_id(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    local_message_id = value.get("localMessageId")
    if isinstance(local_message_id, int):
        return local_message_id
    return None


def _pick_message_key(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    message_key = value.get("messageKey")
    return message_key if isinstance(message_key, str) else None


def _live_event_message(event: dict[str, Any]) -> str:
    scope = event.get("scope")
    reason_code = event.get("reasonCode")
    if scope == "roster":
        changed = int(event.get("changedItemCount") or 0)
        if reason_code == "refresh_error":
            return "Live roster refresh завершился ошибкой."
        if changed > 0:
            return f"Live roster обновлён: изменилось {changed} чатов."
        return "Live roster проверен без новых изменений."

    new_messages = int(event.get("newMessageCount") or 0)
    meaningful = int(event.get("meaningfulMessageCount") or 0)
    if reason_code == "meaningful_signal":
        return f"Live active chat: {meaningful} meaningful signal, reply decision loop запущен."
    if reason_code == "no_new_signal":
        return f"Live active chat: +{new_messages} новых сообщений, reply decision loop пропущен."
    if reason_code == "refresh_error":
        return "Live active chat refresh завершился ошибкой."
    if reason_code == "live_paused":
        return "Live active chat поставлен на паузу."
    if reason_code == "live_resumed":
        return "Live active chat снова live."
    return "Live active chat проверен."


def _live_roster_cache_key(*, search: str | None, filter_key: str, sort_key: str) -> str:
    normalized_search = " ".join((search or "").split()).casefold()
    return f"{filter_key or 'all'}::{sort_key or 'activity'}::{normalized_search}"


def _decorate_live_autopilot_status(payload: dict[str, Any]) -> None:
    live = payload.get("live")
    autopilot = payload.get("autopilot")
    if not isinstance(live, dict) or not isinstance(autopilot, dict):
        return
    decision = autopilot.get("decision") if isinstance(autopilot.get("decision"), dict) else {}
    state = autopilot.get("state") if isinstance(autopilot.get("state"), dict) else {}
    pending = autopilot.get("pendingDraft") if isinstance(autopilot.get("pendingDraft"), dict) else None
    live["decisionStatus"] = decision.get("status") or state.get("status")
    live["decisionReasonCode"] = decision.get("reasonCode") or decision.get("reason_code") or state.get("reasonCode")
    live["decisionAction"] = decision.get("action")
    live["pendingConfirmation"] = bool(
        pending is not None and pending.get("status") == "awaiting_confirmation"
    )
    live["lastAction"] = decision.get("reason") or state.get("reason")


def _preview_text(text: str | None, *, limit: int = 140) -> str | None:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def _build_send_disabled_reason(
    *,
    send_available: bool,
    send_route: dict[str, Any],
    current_disabled_reason: str | None,
) -> str | None:
    if send_available:
        return None
    route_reason = send_route.get("reason")
    if isinstance(route_reason, str) and route_reason:
        return route_reason
    if current_disabled_reason:
        return current_disabled_reason
    if send_route.get("requested") == "new" and send_route.get("effective") != "new":
        return "Отправка через новый Telegram runtime сейчас недоступна."
    if send_route.get("requested") == "new" and send_route.get("status") != "available":
        return (
            str(send_route.get("reason"))
            if isinstance(send_route.get("reason"), str)
            else "Отправка через новый Telegram runtime сейчас недоступна."
        )
    return "Отправка сейчас недоступна."


def _decorate_reply_send_actions(
    payload: dict[str, Any],
    *,
    send_available: bool,
    disabled_reason: str | None,
) -> None:
    reply_payload = payload.get("reply")
    if not isinstance(reply_payload, dict):
        return
    actions = reply_payload.get("actions")
    if not isinstance(actions, dict):
        actions = {}
        reply_payload["actions"] = actions
    actions["send"] = bool(send_available)
    actions["pasteToTelegram"] = False
    actions["markSent"] = bool(actions.get("markSent"))
    actions["disabledReason"] = None if send_available else disabled_reason


def _resolve_targets(component: str | None, *, reverse: bool = False) -> list[str]:
    if component is not None:
        if component not in COMPONENTS:
            raise ValueError(f"Неизвестный component: {component}")
        return [component]
    targets = list(COMPONENTS)
    if reverse:
        targets.reverse()
    return targets
