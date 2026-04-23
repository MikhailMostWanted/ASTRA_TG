import asyncio
from pathlib import Path

from config.settings import Settings
from services.autopilot import AutopilotService
from services.reply_models import ReplyResult, ReplySuggestion
from services.workflow_journal import WorkflowJournalService
from storage.database import bootstrap_database, build_database_runtime
from storage.repositories import ChatRepository, SettingRepository


class FakeSendService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, int | None, str]] = []
        self.next_message_id = 900

    async def send_chat_message(
        self,
        chat,
        *,
        text: str,
        reply_to_source_message_id: int | None = None,
        trigger: str = "manual",
    ):
        self.next_message_id += 1
        self.calls.append((chat.id, text, reply_to_source_message_id, trigger))
        return type(
            "FakeSendResult",
            (),
            {
                "local_chat_id": chat.id,
                "telegram_chat_id": chat.telegram_chat_id,
                "sent_message_id": self.next_message_id,
            },
        )()


def test_autopilot_gating_modes_cooldown_and_weak_trigger(monkeypatch, tmp_path: Path) -> None:
    async def run_assertions() -> None:
        database_path = tmp_path / "autopilot" / "astra.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

        runtime = build_database_runtime(Settings())
        await bootstrap_database(runtime)

        async with runtime.session_factory() as session:
            chats = ChatRepository(session)
            settings = SettingRepository(session)
            chat = await chats.upsert_chat(
                telegram_chat_id=-100888,
                title="Автопилот тест",
                handle="autopilot_test",
                chat_type="group",
                is_enabled=True,
                reply_assist_enabled=False,
                auto_reply_mode="autopilot",
            )
            await session.commit()

            send_service = FakeSendService()
            service = AutopilotService(
                chat_repository=chats,
                setting_repository=settings,
                send_service=send_service,
                journal=WorkflowJournalService(settings),
            )
            reply = _build_reply(chat_id=chat.id, source_message_id=501, confidence=0.86)

            disabled = await service.run_for_chat(
                chat=chat,
                reply_result=reply,
                actor="test",
                write_ready=True,
            )
            assert disabled.decision.allowed is False
            assert "мастер" in disabled.decision.reason.lower()
            assert send_service.calls == []

            await service.update_global_settings(master_enabled=True)
            blocked = await service.run_for_chat(
                chat=chat,
                reply_result=reply,
                actor="test",
                write_ready=True,
            )
            assert blocked.decision.allowed is False
            assert "trusted" in blocked.decision.reason

            await service.update_chat_settings(chat, trusted=True, mode="draft")
            draft = await service.run_for_chat(
                chat=chat,
                reply_result=reply,
                actor="test",
                write_ready=True,
            )
            assert draft.decision.allowed is True
            assert draft.decision.action == "draft"
            overview = await service.build_chat_overview(
                chat=chat,
                reply_result=reply,
                write_ready=True,
            )
            assert overview["pendingDraft"]["text"] == "да, вижу\nсейчас гляну и вернусь"

            await service.update_chat_settings(chat, mode="autopilot")
            low_confidence = await service.run_for_chat(
                chat=chat,
                reply_result=_build_reply(chat_id=chat.id, source_message_id=502, confidence=0.4),
                actor="test",
                write_ready=True,
            )
            assert low_confidence.decision.allowed is False
            assert "ниже порога" in low_confidence.decision.reason

            no_write = await service.run_for_chat(
                chat=chat,
                reply_result=_build_reply(chat_id=chat.id, source_message_id=503, confidence=0.9),
                actor="test",
                write_ready=False,
            )
            assert no_write.decision.allowed is False
            assert "Режим записи" in no_write.decision.reason

            sent = await service.run_for_chat(
                chat=chat,
                reply_result=_build_reply(chat_id=chat.id, source_message_id=504, confidence=0.9),
                actor="test",
                write_ready=True,
            )
            assert sent.send_result is not None
            assert send_service.calls[-1][3] == "autopilot"

            duplicate = await service.run_for_chat(
                chat=chat,
                reply_result=_build_reply(chat_id=chat.id, source_message_id=504, confidence=0.9),
                actor="test",
                write_ready=True,
            )
            assert duplicate.decision.allowed is False
            assert "повторять" in duplicate.decision.reason

            cooldown = await service.run_for_chat(
                chat=chat,
                reply_result=_build_reply(chat_id=chat.id, source_message_id=505, confidence=0.9),
                actor="test",
                write_ready=True,
            )
            assert cooldown.decision.allowed is False
            assert "пауза" in cooldown.decision.reason

        await runtime.dispose()

    asyncio.run(run_assertions())


def _build_reply(*, chat_id: int, source_message_id: int, confidence: float) -> ReplyResult:
    return ReplyResult(
        kind="suggestion",
        chat_id=chat_id,
        chat_title="Автопилот тест",
        chat_reference="@autopilot_test",
        source_sender_name="Ира",
        source_message_preview="Когда будет апдейт?",
        suggestion=ReplySuggestion(
            base_reply_text="да, вижу\nсейчас гляну и вернусь",
            reply_messages=("да, вижу", "сейчас гляну и вернусь"),
            final_reply_messages=("да, вижу", "сейчас гляну и вернусь"),
            style_profile_key="friend_explain",
            style_source="auto",
            style_notes=(),
            persona_applied=True,
            persona_notes=(),
            guardrail_flags=(),
            reason_short="Есть незакрытый вопрос.",
            risk_label="низкий",
            confidence=confidence,
            strategy="мягко ответить",
            source_message_id=source_message_id,
            chat_id=chat_id,
            situation="question",
            source_message_preview="Ира: Когда будет апдейт?",
            focus_label="вопрос",
            focus_reason="Выбран последний вопрос.",
            focus_score=0.88,
            selection_message_count=8,
            source_message_key="telegram:-100500:501",
            source_local_message_id=source_message_id,
            source_runtime_message_id=501,
            source_backend="legacy_local_store",
            reply_opportunity_mode="direct_reply",
            reply_opportunity_reason="Последний входящий сигнал без ответа.",
            reply_recommended=True,
            few_shot_found=True,
            few_shot_match_count=1,
            few_shot_notes=("Нашёл похожий ответ.",),
        ),
    )
