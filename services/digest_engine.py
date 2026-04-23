from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.logging import get_logger, log_event
from services.digest_builder import DigestBuilder
from services.digest_formatter import DigestFormatter
from services.digest_target import DigestTargetService, DigestTargetSnapshot
from services.digest_window import DigestWindow, parse_digest_window
from services.providers.digest_refiner import DigestLLMRefiner
from services.providers.models import LLMDecisionReason
from storage.repositories import DigestRepository, MessageRepository, SettingRepository


LOGGER = get_logger(__name__)


class MessageSenderProtocol(Protocol):
    async def send_message(self, chat_id: int, text: str) -> "MessageSendResultProtocol": ...


class MessageSendResultProtocol(Protocol):
    message_id: int


@dataclass(frozen=True, slots=True)
class DigestExecutionPlan:
    window: DigestWindow
    target: DigestTargetSnapshot
    preview_chunks: list[str]
    target_chunks: list[str]
    digest_id: int | None
    message_count: int
    source_count: int
    summary_short: str
    llm_refine_requested: bool = False
    llm_refine_applied: bool = False
    llm_refine_provider: str | None = None
    llm_refine_notes: tuple[str, ...] = ()
    llm_refine_guardrail_flags: tuple[str, ...] = ()
    llm_refine_baseline_summary_short: str | None = None
    llm_refine_baseline_overview_lines: tuple[str, ...] = ()
    llm_refine_baseline_key_source_lines: tuple[str, ...] = ()
    llm_refine_raw_candidate: str | None = None
    llm_refine_decision_reason: LLMDecisionReason | None = None

    @property
    def has_digest(self) -> bool:
        return self.digest_id is not None


@dataclass(frozen=True, slots=True)
class DigestPublishResult:
    notice: str | None


@dataclass(slots=True)
class DigestEngineService:
    message_repository: MessageRepository
    digest_repository: DigestRepository
    setting_repository: SettingRepository
    builder: DigestBuilder
    formatter: DigestFormatter
    digest_refiner: DigestLLMRefiner | None = None

    async def build_manual_digest(
        self,
        window_argument: str | None,
        *,
        now=None,
        use_provider_improvement: bool | None = None,
    ) -> DigestExecutionPlan:
        window = parse_digest_window(window_argument, now=now)
        target = await DigestTargetService(self.setting_repository).get_target()
        should_try_provider = await self._should_use_provider_improvement(use_provider_improvement)
        log_event(
            LOGGER,
            20,
            "digest.build.started",
            "Начата ручная сборка digest.",
            window=window.label,
            target_configured=target.is_configured,
            llm_requested=should_try_provider,
        )
        message_counts = await self.message_repository.count_messages_by_digest_chat(
            window_start=window.start,
            window_end=window.end,
        )
        records = await self.message_repository.get_messages_for_digest(
            window_start=window.start,
            window_end=window.end,
        )
        if not records:
            log_event(
                LOGGER,
                20,
                "digest.build.empty",
                "Для digest не найдено сообщений.",
                window=window.label,
            )
            rendered = self.formatter.format_empty_window(window_label=window.label)
            await self._record_generation_meta(
                digest_id=None,
                window_label=window.label,
                llm_requested=should_try_provider,
                llm_applied=False,
                llm_provider=None,
                llm_notes=(),
                llm_flags=(),
                summary_short=f"За {window.label} по активным digest-источникам сообщений не найдено.",
                llm_baseline_summary_short=None,
                llm_baseline_overview_lines=(),
                llm_baseline_key_source_lines=(),
                llm_raw_candidate=None,
                llm_decision_reason=None,
            )
            return DigestExecutionPlan(
                window=window,
                target=target,
                preview_chunks=rendered.chunks,
                target_chunks=[],
                digest_id=None,
                message_count=0,
                source_count=0,
                summary_short=f"За {window.label} по активным digest-источникам сообщений не найдено.",
            )

        build_result = self.builder.build(
            window=window,
            records=records,
            message_counts=message_counts,
        )
        llm_baseline_summary_short = build_result.summary_short
        llm_baseline_overview_lines = tuple(build_result.overview_lines)
        llm_baseline_key_source_lines = tuple(build_result.key_source_lines)
        llm_requested = False
        llm_applied = False
        llm_notes: tuple[str, ...] = ()
        llm_flags: tuple[str, ...] = ()
        llm_provider_name: str | None = None
        llm_raw_candidate: str | None = None
        llm_decision_reason: LLMDecisionReason | None = None
        if should_try_provider and self.digest_refiner is not None:
            refinement = await self.digest_refiner.refine(build_result)
            llm_requested = refinement.requested
            llm_applied = refinement.applied
            llm_notes = refinement.notes
            llm_flags = refinement.flags
            llm_provider_name = refinement.provider_name
            llm_baseline_summary_short = (
                refinement.baseline_summary_short or llm_baseline_summary_short
            )
            llm_baseline_overview_lines = (
                refinement.baseline_overview_lines or llm_baseline_overview_lines
            )
            llm_baseline_key_source_lines = (
                refinement.baseline_key_source_lines or llm_baseline_key_source_lines
            )
            llm_raw_candidate = refinement.raw_candidate_text
            llm_decision_reason = refinement.decision_reason
            build_result = refinement.build_result
            if llm_requested and not llm_applied:
                log_event(
                    LOGGER,
                    30,
                    "digest.provider.fallback",
                    "Улучшение дайджеста провайдером не применено, оставлен детерминированный дайджест.",
                    provider_name=llm_provider_name,
                )
        rendered = self.formatter.format(build_result)
        digest = await self.digest_repository.create_digest(
            chat_id=None,
            window_start=window.start,
            window_end=window.end,
            summary_short=build_result.summary_short,
            summary_long=rendered.full_text,
            items=build_result.to_digest_items(),
        )
        await self._record_generation_meta(
            digest_id=digest.id,
            window_label=window.label,
            llm_requested=llm_requested,
            llm_applied=llm_applied,
            llm_provider=llm_provider_name,
            llm_notes=llm_notes,
            llm_flags=llm_flags,
            summary_short=build_result.summary_short,
            llm_baseline_summary_short=llm_baseline_summary_short,
            llm_baseline_overview_lines=llm_baseline_overview_lines,
            llm_baseline_key_source_lines=llm_baseline_key_source_lines,
            llm_raw_candidate=llm_raw_candidate,
            llm_decision_reason=llm_decision_reason,
        )
        log_event(
            LOGGER,
            20,
            "digest.build.completed",
            "Digest собран и сохранён.",
            digest_id=digest.id,
            message_count=build_result.total_messages,
            source_count=build_result.source_count,
        )
        return DigestExecutionPlan(
            window=window,
            target=target,
            preview_chunks=rendered.chunks,
            target_chunks=rendered.chunks,
            digest_id=digest.id,
            message_count=build_result.total_messages,
            source_count=build_result.source_count,
            summary_short=build_result.summary_short,
            llm_refine_requested=llm_requested,
            llm_refine_applied=llm_applied,
            llm_refine_provider=llm_provider_name,
            llm_refine_notes=llm_notes,
            llm_refine_guardrail_flags=llm_flags,
            llm_refine_baseline_summary_short=llm_baseline_summary_short,
            llm_refine_baseline_overview_lines=llm_baseline_overview_lines,
            llm_refine_baseline_key_source_lines=llm_baseline_key_source_lines,
            llm_refine_raw_candidate=llm_raw_candidate,
            llm_refine_decision_reason=llm_decision_reason,
        )

    async def _should_use_provider_improvement(
        self,
        use_provider_improvement: bool | None,
    ) -> bool:
        if use_provider_improvement is not None:
            return use_provider_improvement
        if self.digest_refiner is None:
            return False
        status = await self.digest_refiner.provider_manager.get_status()
        return bool(status.digest_refine_available)

    async def _record_generation_meta(
        self,
        *,
        digest_id: int | None,
        window_label: str,
        llm_requested: bool,
        llm_applied: bool,
        llm_provider: str | None,
        llm_notes: tuple[str, ...],
        llm_flags: tuple[str, ...],
        summary_short: str,
        llm_baseline_summary_short: str | None,
        llm_baseline_overview_lines: tuple[str, ...],
        llm_baseline_key_source_lines: tuple[str, ...],
        llm_raw_candidate: str | None,
        llm_decision_reason: LLMDecisionReason | None,
    ) -> None:
        mode = "deterministic"
        label = "Детерминированный"
        if llm_applied:
            mode = "llm_refine"
            label = "LLM-улучшение"
        elif llm_requested and llm_decision_reason is not None and llm_decision_reason.source == "guardrails":
            mode = "rejected_by_guardrails"
            label = "Отклонён guardrails"
        elif llm_requested:
            mode = "fallback"
            label = "Откат к детерминированному"

        await self.setting_repository.set_value(
            key="digest.last_run_meta",
            value_json={
                "digest_id": digest_id,
                "window": window_label,
                "mode": mode,
                "label": label,
                "llm_requested": llm_requested,
                "llm_applied": llm_applied,
                "provider": llm_provider,
                "notes": list(llm_notes),
                "flags": list(llm_flags),
                "summary_short": summary_short,
                "debug": {
                    "mode": mode,
                    "baseline": {
                        "summary_short": llm_baseline_summary_short,
                        "overview_lines": list(llm_baseline_overview_lines),
                        "key_source_lines": list(llm_baseline_key_source_lines),
                    },
                    "raw_candidate": llm_raw_candidate,
                    "decision_reason": (
                        {
                            "source": llm_decision_reason.source,
                            "code": llm_decision_reason.code,
                            "summary": llm_decision_reason.summary,
                            "detail": llm_decision_reason.detail,
                            "flags": list(llm_decision_reason.flags),
                        }
                        if llm_decision_reason is not None
                        else None
                    ),
                },
            },
            value_text=None,
        )


@dataclass(slots=True)
class DigestPublisherService:
    digest_repository: DigestRepository

    async def publish(
        self,
        *,
        plan: DigestExecutionPlan,
        preview_chat_id: int,
        sender: MessageSenderProtocol,
    ) -> DigestPublishResult:
        log_event(
            LOGGER,
            20,
            "digest.publish.started",
            "Начата публикация digest.",
            digest_id=plan.digest_id,
            preview_chat_id=preview_chat_id,
            target_chat_id=plan.target.chat_id,
        )
        preview_messages = await _send_chunks(
            sender=sender,
            chat_id=preview_chat_id,
            chunks=plan.preview_chunks,
        )
        digest_id = plan.digest_id
        if digest_id is None:
            return DigestPublishResult(notice=None)
        target_chat_id = plan.target.chat_id
        if target_chat_id is None:
            return DigestPublishResult(
                notice="Digest target не задан, сводка показана только в текущем чате."
            )

        if target_chat_id == preview_chat_id:
            if preview_messages:
                await self.digest_repository.mark_delivered(
                    digest_id,
                    delivered_to_chat_id=preview_chat_id,
                    delivered_message_id=preview_messages[0].message_id,
                )
            return DigestPublishResult(
                notice="Digest target совпадает с текущим чатом, отдельная публикация не понадобилась."
            )

        delivered_messages = await _send_chunks(
            sender=sender,
            chat_id=target_chat_id,
            chunks=plan.target_chunks,
        )
        if delivered_messages:
            await self.digest_repository.mark_delivered(
                digest_id,
                delivered_to_chat_id=target_chat_id,
                delivered_message_id=delivered_messages[0].message_id,
            )
        target_label = plan.target.label or str(target_chat_id)
        log_event(
            LOGGER,
            20,
            "digest.publish.completed",
            "Digest опубликован.",
            digest_id=digest_id,
            target_label=target_label,
        )
        return DigestPublishResult(notice=f"Digest также отправлен в {target_label}.")


async def _send_chunks(
    *,
    sender: MessageSenderProtocol,
    chat_id: int,
    chunks: list[str],
) -> list[MessageSendResultProtocol]:
    sent_messages: list[MessageSendResultProtocol] = []
    for chunk in chunks:
        sent_messages.append(await sender.send_message(chat_id, chunk))
    return sent_messages
