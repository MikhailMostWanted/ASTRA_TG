from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.digest_builder import DigestBuildResult, DigestBuilder
from services.digest_formatter import DigestFormatter
from services.digest_target import DigestTargetService, DigestTargetSnapshot
from services.digest_window import DigestWindow, parse_digest_window
from services.providers.digest_refiner import DigestLLMRefiner
from storage.repositories import DigestRepository, MessageRepository, SettingRepository


class MessageSenderProtocol(Protocol):
    async def send_message(self, chat_id: int, text: str):
        """Отправляет сообщение в Telegram и возвращает объект с message_id."""


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
        message_counts = await self.message_repository.count_messages_by_digest_chat(
            window_start=window.start,
            window_end=window.end,
        )
        records = await self.message_repository.get_messages_for_digest(
            window_start=window.start,
            window_end=window.end,
        )
        if not records:
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
        rendered = self.formatter.format(build_result)
        digest = await self.digest_repository.create_digest(
            chat_id=None,
            window_start=window.start,
            window_end=window.end,
            summary_short=build_result.summary_short,
            summary_long=rendered.full_text,
            items=build_result.to_digest_items(),
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
        preview_messages = await _send_chunks(
            sender=sender,
            chat_id=preview_chat_id,
            chunks=plan.preview_chunks,
        )
        if not plan.has_digest:
            return DigestPublishResult(notice=None)
        if not plan.target.is_configured:
            return DigestPublishResult(
                notice="Digest target не задан, сводка показана только в текущем чате."
            )

        if plan.target.chat_id == preview_chat_id:
            if preview_messages:
                await self.digest_repository.mark_delivered(
                    plan.digest_id,
                    delivered_to_chat_id=preview_chat_id,
                    delivered_message_id=preview_messages[0].message_id,
                )
            return DigestPublishResult(
                notice="Digest target совпадает с текущим чатом, отдельная публикация не понадобилась."
            )

        delivered_messages = await _send_chunks(
            sender=sender,
            chat_id=plan.target.chat_id,
            chunks=plan.target_chunks,
        )
        if delivered_messages:
            await self.digest_repository.mark_delivered(
                plan.digest_id,
                delivered_to_chat_id=plan.target.chat_id,
                delivered_message_id=delivered_messages[0].message_id,
            )
        target_label = plan.target.label or str(plan.target.chat_id)
        return DigestPublishResult(notice=f"Digest также отправлен в {target_label}.")


async def _send_chunks(
    *,
    sender: MessageSenderProtocol,
    chat_id: int,
    chunks: list[str],
) -> list[object]:
    sent_messages: list[object] = []
    for chunk in chunks:
        sent_messages.append(await sender.send_message(chat_id, chunk))
    return sent_messages
