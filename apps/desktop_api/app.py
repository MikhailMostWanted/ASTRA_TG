from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Any
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from apps.cli.desktop import DESKTOP_API_PID_PATH
from config.settings import Settings
from fullaccess.cache import avatar_base_path, find_cached_variant, media_preview_base_path
from fullaccess.client import close_managed_fullaccess_clients
from storage.database import bootstrap_database, build_database_runtime

from .bridge import DesktopBridge


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class SourceCreateRequest(BaseModel):
    reference: str | None = None
    title: str | None = None
    chat_type: str | None = None


class FullAccessLoginRequest(BaseModel):
    code: str = Field(min_length=1)
    password: str | None = None


class FullAccessSyncRequest(BaseModel):
    reference: str = Field(min_length=1)


class MemoryRebuildRequest(BaseModel):
    reference: str | None = None


class DigestRunRequest(BaseModel):
    window: str | None = None
    use_provider_improvement: bool | None = None


class DigestTargetRequest(BaseModel):
    reference: str | None = None
    label: str | None = None


class ReminderScanRequest(BaseModel):
    window_argument: str | None = None
    source_reference: str | None = None


def create_app(
    settings: Settings | None = None,
    *,
    runtime=None,
) -> FastAPI:
    effective_settings = settings or Settings()
    owned_runtime = runtime is None
    effective_runtime = runtime or build_database_runtime(effective_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await bootstrap_database(effective_runtime)
        pid_path = _desktop_api_pid_path()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        _app.state.bridge = DesktopBridge(
            settings=effective_settings,
            runtime=effective_runtime,
        )
        try:
            yield
        finally:
            pid_path.unlink(missing_ok=True)
            await close_managed_fullaccess_clients()
            if owned_runtime:
                await effective_runtime.dispose()

    app = FastAPI(
        title="Astra Desktop API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "name": "astra-desktop-api",
            "version": "0.1.0",
        }

    @app.get("/api/media/avatars/{telegram_chat_id}")
    async def media_avatar(telegram_chat_id: int):
        cached = find_cached_variant(
            avatar_base_path(effective_settings.fullaccess_session_file, telegram_chat_id)
        )
        if cached is None:
            raise HTTPException(status_code=404, detail="Аватар пока не кеширован.")
        return FileResponse(cached)

    @app.get("/api/media/messages/{telegram_chat_id}/{telegram_message_id}")
    async def media_message_preview(
        telegram_chat_id: int,
        telegram_message_id: int,
    ):
        cached = find_cached_variant(
            media_preview_base_path(
                effective_settings.fullaccess_session_file,
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
            )
        )
        if cached is None:
            raise HTTPException(status_code=404, detail="Preview для этого медиа пока не кеширован.")
        return FileResponse(cached)

    @app.get("/api/dashboard")
    async def dashboard() -> dict[str, Any]:
        return await _bridge(app).get_dashboard()

    @app.get("/api/ops")
    async def ops_overview(
        tail: int = Query(default=80, ge=10, le=400),
    ) -> dict[str, Any]:
        return await _bridge(app).get_ops_overview(tail=tail)

    @app.get("/api/chats")
    async def chats(
        search: str | None = None,
        filter_key: str = Query(default="all", alias="filter"),
        sort_key: str = Query(default="activity", alias="sort"),
    ) -> dict[str, Any]:
        return await _bridge(app).list_chats(
            search=search,
            filter_key=filter_key,
            sort_key=sort_key,
        )

    @app.get("/api/chats/{chat_id}/messages")
    async def chat_messages(
        chat_id: int,
        limit: int = Query(default=80, ge=10, le=200),
    ) -> dict[str, Any]:
        return await _call_with_lookup(app, lambda: _bridge(app).get_chat_messages(chat_id, limit=limit))

    @app.get("/api/chats/{chat_id}/workspace")
    async def chat_workspace(
        chat_id: int,
        limit: int = Query(default=80, ge=10, le=200),
    ) -> dict[str, Any]:
        return await _call_with_lookup(app, lambda: _bridge(app).get_chat_workspace(chat_id, limit=limit))

    @app.post("/api/chats/{chat_id}/reply-preview")
    async def reply_preview(
        chat_id: int,
        use_provider_refinement: bool | None = None,
    ) -> dict[str, Any]:
        return await _call_with_lookup(
            app,
            lambda: _bridge(app).get_reply_preview(
                chat_id,
                use_provider_refinement=use_provider_refinement,
            ),
        )

    @app.get("/api/sources")
    async def sources() -> dict[str, Any]:
        return await _bridge(app).list_sources()

    @app.post("/api/sources")
    async def add_source(payload: SourceCreateRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).add_source(
                reference=payload.reference,
                title=payload.title,
                chat_type=payload.chat_type,
            ),
        )

    @app.post("/api/sources/{chat_id}/enable")
    async def enable_source(chat_id: int) -> dict[str, Any]:
        return await _call_with_lookup(
            app,
            lambda: _bridge(app).set_source_enabled(chat_id, is_enabled=True),
        )

    @app.post("/api/sources/{chat_id}/disable")
    async def disable_source(chat_id: int) -> dict[str, Any]:
        return await _call_with_lookup(
            app,
            lambda: _bridge(app).set_source_enabled(chat_id, is_enabled=False),
        )

    @app.post("/api/sources/{chat_id}/sync")
    async def sync_source(chat_id: int) -> dict[str, Any]:
        return await _call_with_lookup(app, lambda: _bridge(app).sync_source(chat_id))

    @app.get("/api/fullaccess")
    async def fullaccess() -> dict[str, Any]:
        return await _bridge(app).get_fullaccess_overview()

    @app.post("/api/fullaccess/request-code")
    async def fullaccess_request_code() -> dict[str, Any]:
        return await _call_with_value_error(app, _bridge(app).request_fullaccess_code)

    @app.post("/api/fullaccess/login")
    async def fullaccess_login(payload: FullAccessLoginRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).complete_fullaccess_login(
                code=payload.code,
                password=payload.password,
            ),
        )

    @app.post("/api/fullaccess/logout")
    async def fullaccess_logout() -> dict[str, Any]:
        return await _bridge(app).logout_fullaccess()

    @app.get("/api/fullaccess/chats")
    async def fullaccess_chats(
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        return await _call_with_value_error(app, lambda: _bridge(app).list_fullaccess_chats(limit=limit))

    @app.post("/api/fullaccess/sync")
    async def fullaccess_sync(payload: FullAccessSyncRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).sync_fullaccess_chat(reference=payload.reference),
        )

    @app.get("/api/memory")
    async def memory(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return await _bridge(app).get_memory_overview(limit=limit)

    @app.post("/api/memory/rebuild")
    async def memory_rebuild(payload: MemoryRebuildRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).rebuild_memory(reference=payload.reference),
        )

    @app.get("/api/digest")
    async def digest(
        limit: int = Query(default=6, ge=1, le=20),
    ) -> dict[str, Any]:
        return await _bridge(app).get_digest_overview(limit=limit)

    @app.post("/api/digest/run")
    async def digest_run(payload: DigestRunRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).run_digest(
                window=payload.window,
                use_provider_improvement=payload.use_provider_improvement,
            ),
        )

    @app.post("/api/digest/target")
    async def digest_target(payload: DigestTargetRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).set_digest_target(
                reference=payload.reference,
                label=payload.label,
            ),
        )

    @app.get("/api/reminders")
    async def reminders() -> dict[str, Any]:
        return await _bridge(app).get_reminders_overview()

    @app.post("/api/reminders/scan")
    async def reminders_scan(payload: ReminderScanRequest) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).scan_reminders(
                window_argument=payload.window_argument,
                source_reference=payload.source_reference,
            ),
        )

    @app.get("/api/logs")
    async def logs(
        component: str | None = None,
        tail: int = Query(default=80, ge=10, le=400),
    ) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).get_logs(component=component, tail=tail),
        )

    @app.post("/api/operations/{action}")
    async def operations(
        action: str,
        component: str | None = None,
    ) -> dict[str, Any]:
        return await _call_with_value_error(
            app,
            lambda: _bridge(app).run_operation(action, component=component),
        )

    return app


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    uvicorn.run(
        "apps.desktop_api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=False,
    )


def main() -> int:
    run_server()
    return 0


def _bridge(app: FastAPI) -> DesktopBridge:
    return app.state.bridge


def _desktop_api_pid_path() -> Path:
    raw_path = (os.environ.get("ASTRA_DESKTOP_API_PID_PATH") or "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return DESKTOP_API_PID_PATH


async def _call_with_lookup(app: FastAPI, fn):
    try:
        return await fn()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


async def _call_with_value_error(app: FastAPI, fn):
    try:
        return await fn()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
