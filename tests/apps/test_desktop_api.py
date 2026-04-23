import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from apps.desktop_api.app import create_app
from apps.desktop_api.bridge import DesktopBridge
from config.settings import Settings
from fullaccess.models import (
    FullAccessChatSummary,
    FullAccessLoginResult,
    FullAccessLogoutResult,
    FullAccessStatusReport,
    FullAccessSyncResult,
)
from services.operational_state import OperationalStateService
from services.providers.models import LLMDecisionReason
from services.reply_models import ReplyResult, ReplySuggestion
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import (
    ChatMemoryRepository,
    ChatRepository,
    DigestRepository,
    MessageRepository,
    PersonMemoryRepository,
    ReminderRepository,
    SettingRepository,
    TaskRepository,
)


def test_desktop_api_dashboard_chats_and_reply_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, seeded = await _seed_runtime(monkeypatch, tmp_path)
        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            dashboard = client.get("/api/dashboard")
            assert dashboard.status_code == 200
            dashboard_payload = dashboard.json()
            assert dashboard_payload["database"]["available"] is True
            assert any(card["key"] == "sources" for card in dashboard_payload["statusCards"])
            assert dashboard_payload["summary"]["readyChecks"] >= 1

            chats = client.get("/api/chats", params={"search": "продукта"})
            assert chats.status_code == 200
            chat_payload = chats.json()
            assert chat_payload["count"] == 1
            assert chat_payload["items"][0]["title"] == "Команда продукта"
            assert chat_payload["items"][0]["messageCount"] == 3

            messages = client.get(f"/api/chats/{seeded['chat_id']}/messages")
            assert messages.status_code == 200
            messages_payload = messages.json()
            assert len(messages_payload["messages"]) == 3
            assert messages_payload["messages"][-1]["preview"].startswith("Когда сможешь")

            workspace = client.get(f"/api/chats/{seeded['chat_id']}/workspace")
            assert workspace.status_code == 200
            workspace_payload = workspace.json()
            assert workspace_payload["chat"]["title"] == "Команда продукта"
            assert len(workspace_payload["messages"]) == 3
            assert workspace_payload["freshness"]["mode"] == "local"
            assert workspace_payload["freshness"]["syncError"] is None
            assert workspace_payload["reply"]["suggestion"]["llmStatus"]["mode"] == "deterministic"
            assert workspace_payload["reply"]["suggestion"]["llmDebug"]["baselineText"]
            assert workspace_payload["reply"]["suggestion"]["replyOpportunityReason"]
            assert workspace_payload["reply"]["suggestion"]["variants"]

            reply = client.post(f"/api/chats/{seeded['chat_id']}/reply-preview")
            assert reply.status_code == 200
            reply_payload = reply.json()
            assert reply_payload["kind"] == "suggestion"
            assert reply_payload["suggestion"]["focusReason"]
            assert reply_payload["suggestion"]["replyText"]
            assert reply_payload["suggestion"]["llmStatus"]["label"] == "Детерминированный"
            assert reply_payload["suggestion"]["llmDebug"]["rawCandidate"] is None
            assert reply_payload["suggestion"]["variants"][0]["label"] == "Основной"
            assert reply_payload["actions"]["copy"] is True
            assert reply_payload["actions"]["pasteToTelegram"] is False

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_memory_digest_reminders_sources_and_fullaccess(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, seeded = await _seed_runtime(monkeypatch, tmp_path)
        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            memory = client.get("/api/memory")
            assert memory.status_code == 200
            memory_payload = memory.json()
            assert memory_payload["summary"]["chatCards"] == 1
            assert memory_payload["items"][0]["chatTitle"] == "Команда продукта"

            digest = client.get("/api/digest")
            assert digest.status_code == 200
            digest_payload = digest.json()
            assert digest_payload["latest"]["summaryShort"].startswith("За 24h")
            assert digest_payload["target"]["label"] == "@digest_channel"
            assert digest_payload["generation"]["mode"] == "deterministic"
            assert digest_payload["generation"]["label"] == "Детерминированный"
            assert digest_payload["generation"]["debug"]["baseline"]["summary_short"].startswith("За 24h")

            reminders = client.get("/api/reminders")
            assert reminders.status_code == 200
            reminders_payload = reminders.json()
            assert reminders_payload["summary"]["activeReminderCount"] == 1
            assert reminders_payload["tasks"][0]["title"] == "Скинуть финальный файл"

            add_source = client.post(
                "/api/sources",
                json={
                    "reference": "-100500",
                    "title": "Новый канал",
                    "chat_type": "group",
                },
            )
            assert add_source.status_code == 200
            add_source_payload = add_source.json()
            assert add_source_payload["source"]["title"] == "Новый канал"
            new_chat_id = add_source_payload["source"]["id"]

            disable_source = client.post(f"/api/sources/{new_chat_id}/disable")
            assert disable_source.status_code == 200
            assert disable_source.json()["source"]["enabled"] is False

            fullaccess = client.get("/api/fullaccess")
            assert fullaccess.status_code == 200
            fullaccess_payload = fullaccess.json()
            assert fullaccess_payload["localLoginCommand"] == "astratg fullaccess login"
            assert fullaccess_payload["status"]["enabled"] is False

            ops = client.get("/api/ops")
            assert ops.status_code == 200
            ops_payload = ops.json()
            assert "doctor" in ops_payload
            assert ops_payload["doctor"]["warnings"] is not None

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_reply_payload_includes_rejected_llm_candidate_debug(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, seeded = await _seed_runtime(monkeypatch, tmp_path)

        class FakeReplyService:
            async def build_reply(self, reference: str, *, use_provider_refinement: bool | None = None) -> ReplyResult:
                return ReplyResult(
                    kind="suggestion",
                    chat_id=seeded["chat_id"],
                    chat_title="Команда продукта",
                    chat_reference=reference,
                    source_sender_name="Анна",
                    source_message_preview="Когда сможешь скинуть финальный файл по бюджету?",
                    suggestion=ReplySuggestion(
                        base_reply_text="Понял, посмотрю и вернусь.",
                        reply_messages=("Понял, посмотрю и вернусь.",),
                        final_reply_messages=("Понял, посмотрю и вернусь.",),
                        style_profile_key="friend_explain",
                        style_source="auto",
                        style_notes=(),
                        persona_applied=True,
                        persona_notes=(),
                        guardrail_flags=(),
                        reason_short="Есть открытый вопрос.",
                        risk_label="низкий",
                        confidence=0.82,
                        strategy="мягко ответить",
                        source_message_id=3,
                        chat_id=seeded["chat_id"],
                        situation="question",
                        source_message_preview="Анна: Когда сможешь скинуть финальный файл по бюджету?",
                        focus_label="вопрос",
                        focus_reason="Выбран последний незакрытый вопрос.",
                        reply_opportunity_mode="follow_up_after_self",
                        reply_opportunity_reason="Несмотря на последнее исходящее, в теме остался незакрытый хвост.",
                        few_shot_found=False,
                        few_shot_match_count=0,
                        few_shot_notes=(),
                        llm_refine_requested=True,
                        llm_refine_applied=False,
                        llm_refine_provider="openai_compatible",
                        llm_refine_notes=("LLM-кандидат отклонён guardrails.",),
                        llm_refine_guardrail_flags=("слишком_литературно",),
                        llm_refine_baseline_messages=("Понял, посмотрю и вернусь.",),
                        llm_refine_raw_candidate="В данном случае благодарю за терпение, завтра утром отправлю файл на 25 страниц!!!",
                        llm_refine_decision_reason=LLMDecisionReason(
                            source="guardrails",
                            code="guardrails_rejected",
                            summary="LLM-кандидат для reply отклонён guardrails.",
                            detail="Сработали guardrails: слишком_литературно. Сохранена детерминированная база.",
                            flags=("слишком_литературно",),
                        ),
                    ),
                )

        monkeypatch.setattr(DesktopBridge, "_build_reply_service", lambda self, session: FakeReplyService())

        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            reply = client.post(f"/api/chats/{seeded['chat_id']}/reply-preview")
            assert reply.status_code == 200
            payload = reply.json()
            assert payload["suggestion"]["llmStatus"]["mode"] == "rejected_by_guardrails"
            assert payload["suggestion"]["llmDebug"]["rawCandidate"].startswith("В данном случае благодарю")
            assert payload["suggestion"]["llmDebug"]["baselineText"] == "Понял, посмотрю и вернусь."
            assert payload["suggestion"]["llmDebug"]["decisionReason"]["source"] == "guardrails"
            assert payload["suggestion"]["llmDebug"]["decisionReason"]["flags"] == ["слишком_литературно"]
            assert payload["suggestion"]["replyOpportunityReason"].startswith("Несмотря на последнее исходящее")

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_send_path_writes_message_and_refreshes_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, seeded = await _seed_runtime(monkeypatch, tmp_path)

        class FakeFullAccessAuthService:
            async def build_status_report(self) -> FullAccessStatusReport:
                return FullAccessStatusReport(
                    enabled=True,
                    api_credentials_configured=True,
                    phone_configured=True,
                    session_path=tmp_path / "fullaccess.session",
                    session_exists=True,
                    authorized=True,
                    telethon_available=True,
                    requested_readonly=False,
                    effective_readonly=False,
                    sync_limit=50,
                    pending_login=False,
                    synced_chat_count=1,
                    synced_message_count=10,
                    ready_for_manual_sync=True,
                    ready_for_manual_send=True,
                    reason="Full-access готов к отправке.",
                )

        class FakeFullAccessSendService:
            def __init__(self, session) -> None:
                self.message_repository = MessageRepository(session)

            async def send_chat_message(
                self,
                chat,
                *,
                text: str,
                reply_to_source_message_id: int | None = None,
                trigger: str = "manual",
            ):
                created = await self.message_repository.create_message(
                    chat_id=chat.id,
                    telegram_message_id=777,
                    sender_id=7,
                    sender_name="Михаил",
                    direction="outbound",
                    source_adapter="fullaccess",
                    source_type="message",
                    sent_at=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
                    raw_text=text,
                    normalized_text=text,
                    reply_to_message_id=reply_to_source_message_id,
                )
                return type(
                    "FakeSendResult",
                    (),
                    {
                        "local_chat_id": chat.id,
                        "telegram_chat_id": chat.telegram_chat_id,
                        "sent_message_id": created.id,
                    },
                )()

        monkeypatch.setattr(
            DesktopBridge,
            "_build_fullaccess_auth_service",
            lambda self, session: FakeFullAccessAuthService(),
        )
        monkeypatch.setattr(
            DesktopBridge,
            "_build_fullaccess_send_service",
            lambda self, session: FakeFullAccessSendService(session),
        )

        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            response = client.post(
                f"/api/chats/{seeded['chat_id']}/send",
                json={
                    "text": "Да, вижу. Сейчас гляну и вернусь.",
                    "source_message_id": seeded["last_message_id"],
                },
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is True
            assert payload["sentMessage"]["text"] == "Да, вижу. Сейчас гляну и вернусь."
            assert payload["workspace"]["messages"][-1]["direction"] == "outbound"
            assert payload["workspace"]["messages"][-1]["text"] == "Да, вижу. Сейчас гляну и вернусь."
            assert payload["workspace"]["reply"]["actions"]["send"] is True

        async with runtime.session_factory() as session:
            journal = await SettingRepository(session).get_value(f"workflow.journal.chat.{seeded['chat_id']}")
            assert isinstance(journal, list)
            assert journal[0]["action"] == "manual_send"

        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_lifecycle_writes_and_removes_pid_file(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        settings, runtime, _ = await _seed_runtime(monkeypatch, tmp_path)
        pid_path = tmp_path / "var" / "run" / "astra-desktop-api.pid"
        monkeypatch.setenv("ASTRA_DESKTOP_API_PID_PATH", str(pid_path))
        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            runtime_payload = response.json()["runtime"]
            assert runtime_payload["targetRegistered"] is False
            assert runtime_payload["routes"]["chatRoster"]["effective"] == "legacy"
            assert runtime_payload["routes"]["sendPath"]["effective"] == "legacy"
            assert pid_path.exists() is True
            assert pid_path.read_text(encoding="utf-8").strip() == str(os.getpid())

        assert pid_path.exists() is False
        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_fullaccess_auth_flow_endpoints(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, _ = await _seed_runtime(monkeypatch, tmp_path)

        class FakeFullAccessAuthService:
            def __init__(self) -> None:
                self.completed_payloads: list[tuple[str, str | None]] = []
                self.request_code_calls = 0
                self.logout_calls = 0

            async def build_status_report(self) -> FullAccessStatusReport:
                return FullAccessStatusReport(
                    enabled=True,
                    api_credentials_configured=True,
                    phone_configured=True,
                    session_path=tmp_path / "fullaccess.session",
                    session_exists=True,
                    authorized=False,
                    telethon_available=True,
                    requested_readonly=True,
                    effective_readonly=True,
                    sync_limit=50,
                    pending_login=True,
                    synced_chat_count=3,
                    synced_message_count=48,
                    ready_for_manual_sync=False,
                    ready_for_manual_send=False,
                    reason="Код уже запрошен. Заверши вход в Astra Desktop на экране Full-access.",
                )

            async def begin_login(self) -> FullAccessLoginResult:
                self.request_code_calls += 1
                return FullAccessLoginResult(
                    kind="code_requested",
                    phone="+79990000000",
                    instructions=("Открой Full-access в Astra Desktop.", "Введи код здесь."),
                )

            async def complete_login(self, code: str, *, password_callback=None) -> FullAccessLoginResult:
                password = password_callback() if password_callback is not None else None
                self.completed_payloads.append((code, password or None))
                return FullAccessLoginResult(
                    kind="authorized",
                    phone="+79990000000",
                )

            async def logout(self) -> FullAccessLogoutResult:
                self.logout_calls += 1
                return FullAccessLogoutResult(
                    session_removed=True,
                    pending_auth_cleared=True,
                )

        fake_service = FakeFullAccessAuthService()
        monkeypatch.setattr(
            DesktopBridge,
            "_build_fullaccess_auth_service",
            lambda self, session: fake_service,
        )

        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            overview = client.get("/api/fullaccess")
            assert overview.status_code == 200
            overview_payload = overview.json()
            assert overview_payload["status"]["pendingLogin"] is True
            assert overview_payload["status"]["reason"].startswith("Код уже запрошен")

            request_code = client.post("/api/fullaccess/request-code")
            assert request_code.status_code == 200
            request_payload = request_code.json()
            assert request_payload["kind"] == "code_requested"
            assert request_payload["phone"] == "+79990000000"

            login = client.post(
                "/api/fullaccess/login",
                json={"code": "24680", "password": "secret-2fa"},
            )
            assert login.status_code == 200
            login_payload = login.json()
            assert login_payload["kind"] == "authorized"
            assert login_payload["phone"] == "+79990000000"

            logout = client.post("/api/fullaccess/logout")
            assert logout.status_code == 200
            assert logout.json() == {
                "sessionRemoved": True,
                "pendingAuthCleared": True,
            }

        assert fake_service.request_code_calls == 1
        assert fake_service.completed_payloads == [("24680", "secret-2fa")]
        assert fake_service.logout_calls == 1
        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_workspace_auto_refreshes_fullaccess_chat(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, _ = await _seed_runtime(monkeypatch, tmp_path)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            fullaccess_chat = await chats.upsert_chat(
                telegram_chat_id=-100777,
                title="Full-access live",
                handle="fullaccess_live",
                chat_type="group",
                is_enabled=True,
                category="fullaccess",
                exclude_from_digest=True,
            )
            await messages.create_message(
                chat_id=fullaccess_chat.id,
                telegram_message_id=1,
                sender_id=31,
                sender_name="Ира",
                direction="inbound",
                source_adapter="fullaccess",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
                raw_text="Есть новый хвост?",
                normalized_text="Есть новый хвост?",
            )
            await session.commit()

        class FakeFullAccessAuthService:
            async def build_status_report(self) -> FullAccessStatusReport:
                return FullAccessStatusReport(
                    enabled=True,
                    api_credentials_configured=True,
                    phone_configured=True,
                    session_path=tmp_path / "fullaccess.session",
                    session_exists=True,
                    authorized=True,
                    telethon_available=True,
                    requested_readonly=True,
                    effective_readonly=True,
                    sync_limit=50,
                    pending_login=False,
                    synced_chat_count=1,
                    synced_message_count=10,
                    ready_for_manual_sync=True,
                    ready_for_manual_send=False,
                    reason="Full-access готов.",
                )

        class FakeFullAccessSyncService:
            def __init__(self, session) -> None:
                self.session = session
                self.calls = 0

            async def sync_chat(self, reference: str, *, trigger: str = "manual") -> FullAccessSyncResult:
                self.calls += 1
                await MessageRepository(self.session).create_message(
                    chat_id=fullaccess_chat.id,
                    telegram_message_id=2,
                    sender_id=31,
                    sender_name="Ира",
                    direction="inbound",
                    source_adapter="fullaccess",
                    source_type="message",
                    sent_at=datetime(2026, 4, 22, 10, 1, tzinfo=timezone.utc),
                    raw_text="Да, это свежий auto-sync хвост.",
                    normalized_text="Да, это свежий auto-sync хвост.",
                )
                await OperationalStateService(SettingRepository(self.session)).record_fullaccess_chat_sync(
                    local_chat_id=fullaccess_chat.id,
                    telegram_chat_id=fullaccess_chat.telegram_chat_id,
                    reference=reference,
                    scanned_count=1,
                    created_count=1,
                    updated_count=0,
                    skipped_count=0,
                    trigger=trigger,
                )
                return FullAccessSyncResult(
                    chat=FullAccessChatSummary(
                        telegram_chat_id=fullaccess_chat.telegram_chat_id,
                        title=fullaccess_chat.title,
                        chat_type=fullaccess_chat.type,
                        username=fullaccess_chat.handle,
                    ),
                    local_chat_id=fullaccess_chat.id,
                    chat_created=False,
                    scanned_count=1,
                    created_count=1,
                    updated_count=0,
                    skipped_count=0,
                )

        fake_sync_service = None

        def build_sync_service(self, session):
            nonlocal fake_sync_service
            fake_sync_service = FakeFullAccessSyncService(session)
            return fake_sync_service

        monkeypatch.setattr(
            DesktopBridge,
            "_build_fullaccess_auth_service",
            lambda self, session: FakeFullAccessAuthService(),
        )
        monkeypatch.setattr(DesktopBridge, "_build_fullaccess_sync_service", build_sync_service)

        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            workspace = client.get(f"/api/chats/{fullaccess_chat.id}/workspace")
            assert workspace.status_code == 200
            workspace_payload = workspace.json()
            assert len(workspace_payload["messages"]) == 2
            assert workspace_payload["messages"][-1]["text"] == "Да, это свежий auto-sync хвост."
            assert workspace_payload["freshness"]["updatedNow"] is True
            assert workspace_payload["freshness"]["syncTrigger"] == "auto"
            assert workspace_payload["freshness"]["syncError"] is None
            assert workspace_payload["freshness"]["label"] == "Хвост обновлён"

        assert fake_sync_service is not None
        assert fake_sync_service.calls == 1
        await runtime.dispose()

    asyncio.run(run_assertions())


def test_desktop_api_workspace_keeps_shell_alive_when_auto_refresh_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def run_assertions() -> None:
        settings, runtime, _ = await _seed_runtime(monkeypatch, tmp_path)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            messages = MessageRepository(session)
            fullaccess_chat = await chats.upsert_chat(
                telegram_chat_id=-100778,
                title="Full-access flaky",
                handle="fullaccess_flaky",
                chat_type="group",
                is_enabled=True,
                category="fullaccess",
                exclude_from_digest=True,
            )
            await messages.create_message(
                chat_id=fullaccess_chat.id,
                telegram_message_id=1,
                sender_id=41,
                sender_name="Оля",
                direction="inbound",
                source_adapter="fullaccess",
                source_type="message",
                sent_at=datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc),
                raw_text="Старый локальный хвост.",
                normalized_text="Старый локальный хвост.",
            )
            await session.commit()

        class FakeFullAccessAuthService:
            async def build_status_report(self) -> FullAccessStatusReport:
                return FullAccessStatusReport(
                    enabled=True,
                    api_credentials_configured=True,
                    phone_configured=True,
                    session_path=tmp_path / "fullaccess.session",
                    session_exists=True,
                    authorized=True,
                    telethon_available=True,
                    requested_readonly=True,
                    effective_readonly=True,
                    sync_limit=50,
                    pending_login=False,
                    synced_chat_count=1,
                    synced_message_count=10,
                    ready_for_manual_sync=True,
                    ready_for_manual_send=False,
                    reason="Full-access готов.",
                )

        class FailingFullAccessSyncService:
            async def sync_chat(self, reference: str, *, trigger: str = "manual") -> FullAccessSyncResult:
                raise ValueError("Telethon timeout while syncing active chat.")

        monkeypatch.setattr(
            DesktopBridge,
            "_build_fullaccess_auth_service",
            lambda self, session: FakeFullAccessAuthService(),
        )
        monkeypatch.setattr(
            DesktopBridge,
            "_build_fullaccess_sync_service",
            lambda self, session: FailingFullAccessSyncService(),
        )

        app = create_app(settings, runtime=runtime)

        with TestClient(app) as client:
            workspace = client.get(f"/api/chats/{fullaccess_chat.id}/workspace")
            assert workspace.status_code == 200
            workspace_payload = workspace.json()
            assert len(workspace_payload["messages"]) == 1
            assert workspace_payload["messages"][0]["text"] == "Старый локальный хвост."
            assert workspace_payload["freshness"]["mode"] == "attention"
            assert workspace_payload["freshness"]["syncError"] == "Telethon timeout while syncing active chat."
            assert "без падения shell" in workspace_payload["freshness"]["detail"]

        await runtime.dispose()

    asyncio.run(run_assertions())


async def _seed_runtime(monkeypatch, tmp_path: Path):
    database_path = tmp_path / "desktop-api" / "astra.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    settings = Settings()
    runtime = build_database_runtime(settings)
    await bootstrap_database(runtime)

    async with runtime.session_factory() as session:
        chats = ChatRepository(session)
        messages = MessageRepository(session)
        chat_memory = ChatMemoryRepository(session)
        people_memory = PersonMemoryRepository(session)
        digests = DigestRepository(session)
        settings_repo = SettingRepository(session)
        tasks = TaskRepository(session)
        reminders = ReminderRepository(session)

        team_chat = await chats.upsert_chat(
            telegram_chat_id=-100300,
            title="Команда продукта",
            handle="product_team",
            chat_type="group",
            is_enabled=True,
        )

        await messages.create_message(
            chat_id=team_chat.id,
            telegram_message_id=1,
            sender_id=7,
            sender_name="Михаил",
            direction="outbound",
            source_adapter="telegram",
            source_type="message",
            sent_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
            raw_text="Смотрю бюджет и вернусь чуть позже.",
            normalized_text="Смотрю бюджет и вернусь чуть позже.",
        )
        await messages.create_message(
            chat_id=team_chat.id,
            telegram_message_id=2,
            sender_id=11,
            sender_name="Анна",
            direction="inbound",
            source_adapter="telegram",
            source_type="message",
            sent_at=datetime(2026, 4, 20, 9, 5, tzinfo=timezone.utc),
            raw_text="Ок, тогда жду апдейт по бюджету.",
            normalized_text="Ок, тогда жду апдейт по бюджету.",
        )
        inbound_two = await messages.create_message(
            chat_id=team_chat.id,
            telegram_message_id=3,
            sender_id=11,
            sender_name="Анна",
            direction="inbound",
            source_adapter="telegram",
            source_type="message",
            sent_at=datetime(2026, 4, 20, 9, 25, tzinfo=timezone.utc),
            raw_text="Когда сможешь скинуть финальный файл по бюджету?",
            normalized_text="Когда сможешь скинуть финальный файл по бюджету?",
        )

        await chat_memory.upsert_chat_memory(
            chat_id=team_chat.id,
            chat_summary_short="Идёт спокойное обсуждение бюджета и финального файла.",
            chat_summary_long="Анна ждёт апдейт по бюджету, вопрос пока остаётся открытым.",
            current_state="спокойное рабочее обсуждение, есть открытые хвосты",
            dominant_topics_json=[{"topic": "бюджет", "mentions": 3}],
            recent_conflicts_json=[],
            pending_tasks_json=["Анна ждёт финальный файл по бюджету."],
            linked_people_json=[{"person_key": "tg:11", "display_name": "Анна", "message_count": 2}],
            last_digest_at=None,
        )
        await people_memory.upsert_person_memory(
            person_key="tg:11",
            display_name="Анна",
            relationship_label="контакт",
            importance_score=84.0,
            last_summary="Регулярно пишет по бюджету и ждёт апдейты.",
            known_facts_json=["Ждёт финальный файл по бюджету."],
            sensitive_topics_json=["деньги и бюджет"],
            open_loops_json=["Ждёт финальный файл по бюджету."],
            interaction_pattern="пишет коротко и часто задаёт вопросы",
        )

        await settings_repo.set_value(key="digest.target.chat_id", value_text="-100999")
        await settings_repo.set_value(key="digest.target.label", value_text="@digest_channel")
        await settings_repo.set_value(key="digest.target.type", value_text="channel")
        digest = await digests.create_digest(
            chat_id=None,
            window_start=datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 21, 0, 0, tzinfo=timezone.utc),
            summary_short="За 24h обсуждали бюджет и финальный файл.",
            summary_long="Главная тема: бюджет. Анна ждёт финальный файл и апдейт по срокам.",
            items=[
                {
                    "source_chat_id": team_chat.id,
                    "source_message_id": inbound_two.id,
                    "title": "Команда продукта",
                    "summary": "Анна ждёт финальный файл и апдейт по бюджету.",
                    "sort_order": 0,
                }
            ],
        )
        await settings_repo.set_value(
            key="digest.last_run_meta",
            value_json={
                "digest_id": digest.id,
                "window": "24h",
                "mode": "deterministic",
                "label": "Детерминированный",
                "llm_requested": False,
                "llm_applied": False,
                "provider": None,
                "notes": [],
                "flags": [],
                "summary_short": "За 24h обсуждали бюджет и финальный файл.",
                "debug": {
                    "mode": "deterministic",
                    "baseline": {
                        "summary_short": "За 24h обсуждали бюджет и финальный файл.",
                        "overview_lines": ["- Главная тема: бюджет."],
                        "key_source_lines": ["- Команда продукта: Анна ждёт финальный файл и апдейт по бюджету."],
                    },
                    "raw_candidate": None,
                    "decision_reason": None,
                },
            },
        )

        task = await tasks.create_task(
            source_chat_id=team_chat.id,
            source_message_id=inbound_two.id,
            title="Скинуть финальный файл",
            summary="Нужно отправить итоговый файл по бюджету.",
            due_at=datetime(2026, 4, 20, 20, 0, tzinfo=timezone.utc),
            suggested_remind_at=datetime(2026, 4, 20, 19, 0, tzinfo=timezone.utc),
            status="active",
            confidence=0.92,
            needs_user_confirmation=False,
        )
        await reminders.create_reminder(
            task_id=task.id,
            remind_at=datetime(2026, 4, 20, 19, 0, tzinfo=timezone.utc),
            status="active",
            payload_json={"task_title": "Скинуть финальный файл"},
        )

        await session.commit()

    return settings, runtime, {
        "chat_id": team_chat.id,
        "digest_id": digest.id,
        "last_message_id": inbound_two.id,
    }
