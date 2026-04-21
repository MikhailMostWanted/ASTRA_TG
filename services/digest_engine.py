from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.logging import get_logger, log_event
from services.digest_builder import DigestBuilder
from services.digest_formatter import DigestFormatter
from services.digest_target import DigestTargetService, DigestTargetSnapshot
from services.digest_window import DigestWindow, parse_digest_window
from services.providers.digest_refiner import DigestLLMRefiner
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
    llm_refine_requested: bool = False
    llm_refine_applied: bool = False
    llm_refine_provider: str | None = None
    llm_refine_notes: tuple[str, ...] = ()
    llm_refine_guardrail_flags: tuple[str, ...] = ()

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
        use_provider_improvement: bool = False,
    ) -> DigestExecutionPlan:
        window = parse_digest_window(window_argument, now=now)
        target = await DigestTargetService(self.setting_repository).get_target()
        log_event(
            LOGGER,
            20,
            "digest.build.started",
            "Начата ручная сборка digest.",
            window=window.label,
            target_configured=target.is_configured,
            llm_requested=use_provider_improvement,
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
            return DigestExecutionPlan(
                window=window,
                target=target,
                preview_chunks=[
                    f"За {window.label} по активным digest-источникам сообщений не найдено."
                ],
                target_chunks=[],
                digest_id=None,
                message_count=0,
                source_count=0,
            )

        build_result = self.builder.build(
            window=window,
            records=records,
            message_counts=message_counts,
        )
        llm_requested = False
        llm_applied = False
        llm_notes: tuple[str, ...] = ()
        llm_flags: tuple[str, ...] = ()
        llm_provider_name: str | None = None
        if use_provider_improvement and self.digest_refiner is not None:
            refinement = await self.digest_refiner.refine(build_result)
            llm_requested = refinement.requested
            llm_applied = refinement.applied
            llm_notes = refinement.notes
            llm_flags = refinement.flags
            llm_provider_name = refinement.provider_name
            build_result = refinement.build_result
            if llm_requested and not llm_applied:
                log_event(
                    LOGGER,
                    30,
                    "digest.provider.fallback",
                    "Digest provider improve не применён, оставлен deterministic digest.",
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
            llm_refine_requested=llm_requested,
            llm_refine_applied=llm_applied,
            llm_refine_provider=llm_provider_name,
            llm_refine_notes=llm_notes,
            llm_refine_guardrail_flags=llm_flags,
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
