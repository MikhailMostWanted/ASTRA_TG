from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from models import Chat, Message
from services.memory_common import build_person_reference, normalize_display_name, tokenize_text
from services.reply_classifier import ReplyClassifier
from services.reply_examples_models import ReplyExamplesRebuildResult
from storage.repositories import ChatRepository, MessageRepository, ReplyExampleRepository


NOISE_MARKERS = {
    "+",
    "++",
    "ок",
    "окей",
    "ага",
    "спс",
    "спасибо",
    "ясно",
    "понял",
    "поняла",
    "принято",
}
FOLLOW_UP_MARKERS = (
    "вернусь",
    "скину",
    "пришлю",
    "напишу",
    "отпишу",
    "проверю",
    "смотрю",
    "гляну",
    "посмотрю",
    "апдейт",
)


@dataclass(slots=True)
class ReplyExamplesBuilder:
    chat_repository: ChatRepository
    message_repository: MessageRepository
    reply_example_repository: ReplyExampleRepository
    classifier: ReplyClassifier = field(default_factory=ReplyClassifier)
    max_reply_gap: timedelta = timedelta(hours=6)
    min_quality_score: float = 0.55
    context_before_limit: int = 3
    max_text_length: int = 700

    async def rebuild(self, reference: str | None = None) -> ReplyExamplesRebuildResult:
        if reference is not None:
            chat = await self.chat_repository.find_chat_by_handle_or_telegram_id(reference)
            if chat is None:
                raise ValueError("Источник не найден. Проверь chat_id или @username.")
            chats = [chat]
            await self.reply_example_repository.delete_for_chat(chat_id=chat.id)
        else:
            chats = [
                chat
                for chat in await self.chat_repository.list_enabled_chats()
                if chat.type != "channel"
            ]
            await self.reply_example_repository.delete_all()

        examples_created = 0
        messages_scanned = 0
        for chat in chats:
            messages = await self.message_repository.get_messages_for_chat(
                chat_id=chat.id,
                ascending=True,
            )
            messages_scanned += len(messages)
            for payload in self._collect_examples(chat=chat, messages=messages):
                await self.reply_example_repository.create_example(**payload)
                examples_created += 1

        return ReplyExamplesRebuildResult(
            examples_created=examples_created,
            chats_processed=len(chats),
            messages_scanned=messages_scanned,
            scope_reference=reference,
        )

    def _collect_examples(
        self,
        *,
        chat: Chat,
        messages: list[Message],
    ) -> list[dict[str, object]]:
        examples: list[dict[str, object]] = []
        pending_inbound: tuple[int, Message, str, list[dict[str, str]]] | None = None

        for index, message in enumerate(messages):
            text = _pick_message_text(message)
            if pending_inbound is not None:
                _, pending_message, _, _ = pending_inbound
                if (message.sent_at - pending_message.sent_at) > self.max_reply_gap:
                    pending_inbound = None

            if message.direction == "inbound":
                if self._is_candidate_inbound(text):
                    pending_inbound = (
                        index,
                        message,
                        text,
                        _build_context_before(messages, index=index, limit=self.context_before_limit),
                    )
                continue

            if pending_inbound is None or message.direction != "outbound":
                continue

            inbound_index, inbound_message, inbound_text, context_before = pending_inbound
            if message.sent_at < inbound_message.sent_at:
                continue
            if (message.sent_at - inbound_message.sent_at) > self.max_reply_gap:
                pending_inbound = None
                continue

            outbound_text = _pick_message_text(message)
            if not self._is_candidate_outbound(outbound_text):
                continue

            quality_score = _compute_quality_score(
                inbound_text=inbound_text,
                outbound_text=outbound_text,
                gap_seconds=max((message.sent_at - inbound_message.sent_at).total_seconds(), 0.0),
            )
            if quality_score < self.min_quality_score:
                continue

            classification = self.classifier.classify_text(
                text=inbound_text,
                chat_state="",
                interaction_pattern="",
                has_open_loops=False,
            )
            examples.append(
                {
                    "chat_id": chat.id,
                    "inbound_message_id": inbound_message.id,
                    "outbound_message_id": message.id,
                    "inbound_text": inbound_text,
                    "outbound_text": outbound_text,
                    "inbound_normalized": inbound_text.casefold(),
                    "outbound_normalized": outbound_text.casefold(),
                    "context_before_json": context_before,
                    "example_type": classification.situation,
                    "source_person_key": _resolve_person_key(chat=chat, message=inbound_message),
                    "quality_score": quality_score,
                }
            )
            pending_inbound = None

        return examples

    def _is_candidate_inbound(self, text: str) -> bool:
        return _is_meaningful_text(text, max_text_length=self.max_text_length)

    def _is_candidate_outbound(self, text: str) -> bool:
        if not _is_meaningful_text(text, max_text_length=self.max_text_length):
            return False
        tokens = tokenize_text(text)
        if len(tokens) < 2 and not any(marker in text.casefold() for marker in FOLLOW_UP_MARKERS):
            return False
        return True


def _build_context_before(
    messages: list[Message],
    *,
    index: int,
    limit: int,
) -> list[dict[str, str]]:
    context_slice = messages[max(0, index - limit) : index]
    rendered: list[dict[str, str]] = []
    for item in context_slice:
        text = _pick_message_text(item)
        if not text:
            continue
        rendered.append(
            {
                "direction": item.direction,
                "sender_name": normalize_display_name(item.sender_name) or "без имени",
                "text": text,
            }
        )
    return rendered


def _is_meaningful_text(text: str, *, max_text_length: int) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return False
    if normalized.startswith("/"):
        return False
    if len(normalized) > max_text_length:
        return False

    tokens = tokenize_text(normalized)
    if normalized.casefold() in NOISE_MARKERS:
        return False
    if len(tokens) >= 2:
        return True
    if "?" in normalized and len(normalized) >= 6:
        return True
    return len(normalized) >= 12 and bool(tokens)


def _compute_quality_score(
    *,
    inbound_text: str,
    outbound_text: str,
    gap_seconds: float,
) -> float:
    inbound_tokens = tokenize_text(inbound_text)
    outbound_tokens = tokenize_text(outbound_text)

    score = 0.42
    score += min(len(inbound_tokens), 8) * 0.03
    score += min(len(outbound_tokens), 10) * 0.028
    if any(marker in outbound_text.casefold() for marker in FOLLOW_UP_MARKERS):
        score += 0.08
    if "?" in inbound_text:
        score += 0.05
    if gap_seconds <= 15 * 60:
        score += 0.08
    elif gap_seconds <= 60 * 60:
        score += 0.04
    elif gap_seconds > 3 * 60 * 60:
        score -= 0.07
    if len(outbound_text) > 380:
        score -= 0.08
    if len(inbound_text) > 420:
        score -= 0.05
    return max(0.0, min(round(score, 2), 0.99))


def _resolve_person_key(*, chat: Chat, message: Message) -> str | None:
    fallback_title = chat.title if chat.type == "private" else None
    fallback_handle = chat.handle if chat.type == "private" else None
    reference = build_person_reference(
        sender_id=message.sender_id,
        sender_name=message.sender_name,
        fallback_title=fallback_title,
        fallback_handle=fallback_handle,
    )
    if reference is None:
        return None
    return reference.person_key


def _pick_message_text(message: Message) -> str:
    return " ".join((message.normalized_text or message.raw_text or "").split()).strip()
