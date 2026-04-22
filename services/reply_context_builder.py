from __future__ import annotations

from dataclasses import dataclass

from models import Chat, Message
from services.memory_common import (
    build_person_reference,
    extract_dominant_topics,
    tokenize_text,
    truncate_text,
)
from services.reply_models import ReplyContext, ReplyContextIssue
from services.reply_signal import (
    has_follow_up_commitment_signal,
    has_emotional_signal,
    has_open_loop_signal,
    has_question_signal,
    has_request_signal,
    has_resolution_signal,
    is_low_signal_text,
    pick_focus_label,
)
from storage.repositories import ChatMemoryRepository, MessageRepository, PersonMemoryRepository


@dataclass(frozen=True, slots=True)
class _ReplyFocusCandidate:
    message: Message
    text: str
    score: float
    focus_label: str
    is_low_signal: bool
    age_from_end: int
    later_meaningful_inbound_count: int
    later_low_signal_inbound_count: int
    later_outbound_count: int
    later_outbound_has_follow_up_commitment: bool


@dataclass(slots=True)
class ReplyContextBuilder:
    message_repository: MessageRepository
    chat_memory_repository: ChatMemoryRepository
    person_memory_repository: PersonMemoryRepository
    context_limit: int = 40
    selection_window: int = 16
    min_messages: int = 3

    async def build(self, chat: Chat) -> ReplyContext | ReplyContextIssue:
        recent_desc = await self.message_repository.get_recent_messages(
            chat_id=chat.id,
            limit=self.context_limit,
        )
        if not recent_desc:
            return ReplyContextIssue(
                code="not_enough_data",
                message=(
                    "Подсказку пока не собрать: в этом чате ещё нет накопленного локального контекста."
                ),
            )

        recent_messages = tuple(reversed(recent_desc))
        latest_message = recent_messages[-1]
        text_messages = [message for message in recent_messages if _pick_message_text(message)]
        if len(text_messages) < self.min_messages:
            return ReplyContextIssue(
                code="not_enough_data",
                message=(
                    "Подсказку пока не собрать: локальных сообщений маловато для внятного контекста. "
                    "Накопи ещё несколько реплик и повтори /reply."
                ),
            )

        focus_candidate = self._select_focus_candidate(recent_messages)
        if focus_candidate is None:
            return ReplyContextIssue(
                code="not_enough_data",
                message=(
                    "Подсказку пока не собрать: не вижу последнего входящего сообщения, "
                    "на которое логично отвечать."
                ),
            )
        target_message = focus_candidate.message

        chat_memory = await self.chat_memory_repository.get_chat_memory(chat.id)
        person_memory = await self._resolve_person_memory(chat, target_message)
        linked_people = await self._resolve_linked_people(chat_memory, person_memory)
        pending_loops = tuple(
            str(item)
            for item in (
                getattr(chat_memory, "pending_tasks_json", None) or []
            )
            if str(item).strip()
        )[:4]
        recent_conflicts = tuple(
            str(item)
            for item in (
                getattr(chat_memory, "recent_conflicts_json", None) or []
            )
            if str(item).strip()
        )[:3]
        topic_hints = self._collect_topic_hints(
            target_message=target_message,
            chat_memory=chat_memory,
            recent_messages=recent_messages,
        )
        reply_opportunity_mode, reply_opportunity_reason = self._build_reply_opportunity(
            recent_messages=recent_messages,
            focus_candidate=focus_candidate,
            pending_loops=pending_loops,
        )

        return ReplyContext(
            chat=chat,
            recent_messages=recent_messages,
            latest_message=latest_message,
            target_message=target_message,
            focus_label=focus_candidate.focus_label,
            focus_reason=self._build_focus_reason(
                recent_messages=recent_messages,
                focus_candidate=focus_candidate,
            ),
            focus_score=focus_candidate.score,
            chat_memory=chat_memory,
            person_memory=person_memory,
            linked_people=linked_people,
            topic_hints=topic_hints,
            pending_loops=pending_loops,
            recent_conflicts=recent_conflicts,
            reply_opportunity_mode=reply_opportunity_mode,
            reply_opportunity_reason=reply_opportunity_reason,
        )

    def _select_focus_candidate(
        self,
        recent_messages: tuple[Message, ...],
    ) -> _ReplyFocusCandidate | None:
        selection_messages = recent_messages[-self.selection_window :]
        inbound_candidates = [
            self._score_focus_candidate(
                message=message,
                age_from_end=(len(selection_messages) - index - 1),
                later_messages=selection_messages[index + 1 :],
            )
            for index, message in enumerate(selection_messages)
            if message.direction == "inbound" and _pick_message_text(message)
        ]
        if not inbound_candidates:
            return None

        return max(
            inbound_candidates,
            key=lambda candidate: (candidate.score, -candidate.age_from_end, candidate.message.id),
        )

    def _score_focus_candidate(
        self,
        *,
        message: Message,
        age_from_end: int,
        later_messages: tuple[Message, ...],
    ) -> _ReplyFocusCandidate:
        text = _pick_message_text(message)
        question_signal = has_question_signal(text)
        request_signal = has_request_signal(text)
        open_loop_signal = has_open_loop_signal(text)
        emotional_signal = has_emotional_signal(text)
        low_signal = is_low_signal_text(text)
        token_count = len(tokenize_text(text))
        later_meaningful_inbound_count = len(
            [
                later_message
                for later_message in later_messages
                if later_message.direction == "inbound"
                and not is_low_signal_text(_pick_message_text(later_message))
            ]
        )
        later_low_signal_inbound_count = len(
            [
                later_message
                for later_message in later_messages
                if later_message.direction == "inbound"
                and is_low_signal_text(_pick_message_text(later_message))
            ]
        )
        later_outbound_messages = [
            later_message
            for later_message in later_messages
            if later_message.direction == "outbound" and _pick_message_text(later_message)
        ]
        later_outbound_has_follow_up_commitment = any(
            has_follow_up_commitment_signal(_pick_message_text(later_message))
            for later_message in later_outbound_messages
        )

        score = 0.18
        if question_signal:
            score += 2.1
        if request_signal:
            score += 1.7
        if open_loop_signal:
            score += 1.0
        if emotional_signal:
            score += 1.3
        if token_count >= 4:
            score += 0.4
        elif token_count >= 2:
            score += 0.2
        if len(text) >= 48:
            score += 0.12
        if message.reply_to_message_id is not None:
            score += 0.15
        score += self._recency_bonus(age_from_end)
        score -= min(0.75, later_meaningful_inbound_count * 0.32)
        if later_low_signal_inbound_count and later_meaningful_inbound_count == 0:
            score += 0.18
        if later_outbound_has_follow_up_commitment:
            score += 0.46
        elif later_outbound_messages and later_meaningful_inbound_count == 0:
            score -= 0.18
        if low_signal:
            score -= 1.6

        return _ReplyFocusCandidate(
            message=message,
            text=text,
            score=round(score, 2),
            focus_label=pick_focus_label(text),
            is_low_signal=low_signal,
            age_from_end=age_from_end,
            later_meaningful_inbound_count=later_meaningful_inbound_count,
            later_low_signal_inbound_count=later_low_signal_inbound_count,
            later_outbound_count=len(later_outbound_messages),
            later_outbound_has_follow_up_commitment=later_outbound_has_follow_up_commitment,
        )

    def _build_focus_reason(
        self,
        *,
        recent_messages: tuple[Message, ...],
        focus_candidate: _ReplyFocusCandidate,
    ) -> str:
        later_inbound_messages = [
            message
            for message in recent_messages
            if message.direction == "inbound" and message.id > focus_candidate.message.id
        ]
        later_low_signal = [
            message
            for message in later_inbound_messages
            if is_low_signal_text(_pick_message_text(message))
        ]
        later_meaningful_count = len(later_inbound_messages) - len(later_low_signal)

        if focus_candidate.is_low_signal:
            return (
                "Сильного reply-trigger рядом нет: последнее входящее выглядит низкосигнальным, "
                "поэтому стратегия «не отвечать» остаётся нормальным вариантом."
            )

        if focus_candidate.later_outbound_has_follow_up_commitment:
            return (
                "Выбран незакрытый вопрос или просьба, которые остались в контексте даже после "
                "твоего более позднего промежуточного апдейта."
            )

        focus_lead = {
            "вопрос": "Выбран последний незакрытый вопрос в свежем окне сообщений.",
            "просьба": "Выбрана последняя незакрытая просьба, где от тебя ожидают действие или апдейт.",
            "незакрытая тема": "Выбрано место, где тема ещё не закрыта и просится короткое продолжение.",
            "эмоциональный сигнал": "Выбрана эмоционально значимая реплика, которую лучше не оставлять без реакции.",
        }.get(
            focus_candidate.focus_label,
            "Выбрана самая сильная смысловая реплика в последних сообщениях.",
        )

        if later_low_signal and later_meaningful_count == 0:
            return (
                f"{focus_lead} Более позднее {_quote_focus_preview(later_low_signal[-1])} "
                "понижено как low-signal."
            )
        if later_meaningful_count > 0:
            return (
                f"{focus_lead} У более поздних реплик сигнал слабее, поэтому фокус оставлен здесь."
            )
        if focus_candidate.age_from_end <= 2:
            return f"{focus_lead} Этот фрагмент всё ещё в самом свежем слое диалога."
        return focus_lead

    def _build_reply_opportunity(
        self,
        *,
        recent_messages: tuple[Message, ...],
        focus_candidate: _ReplyFocusCandidate,
        pending_loops: tuple[str, ...],
    ) -> tuple[str, str]:
        latest_message = recent_messages[-1]
        if latest_message.direction != "outbound":
            return (
                "direct_reply",
                "Последний осмысленный входящий сигнал остаётся без ответа, поэтому reply уместен прямо сейчас.",
            )

        if focus_candidate.is_low_signal:
            return (
                "hold",
                "Последнее сообщение уже было от тебя, а сильного нового повода дописывать сверху не видно.",
            )

        latest_outbound_text = _pick_message_text(latest_message)
        has_follow_up_commitment = has_follow_up_commitment_signal(latest_outbound_text)
        has_resolution = has_resolution_signal(latest_outbound_text)
        has_pending_tail = bool(pending_loops)
        latest_outbound_short = (
            is_low_signal_text(latest_outbound_text)
            or len(tokenize_text(latest_outbound_text)) <= 5
        )

        if has_resolution and focus_candidate.focus_label in {"вопрос", "просьба", "незакрытая тема"}:
            return (
                "hold",
                "Последнее исходящее уже выглядит как закрытие вопроса, поэтому явного незакрытого повода писать ещё раз не видно.",
            )

        if has_pending_tail and (
            focus_candidate.focus_label in {"вопрос", "просьба", "незакрытая тема"}
            or has_follow_up_commitment
        ):
            return (
                "follow_up_after_self",
                "Несмотря на последнее исходящее, в памяти и свежем окне остался незакрытый хвост по теме.",
            )

        if has_follow_up_commitment:
            return (
                "follow_up_after_self",
                "Последнее исходящее выглядит как промежуточный апдейт или обещание вернуться, "
                "поэтому follow-up всё ещё уместен.",
            )

        if focus_candidate.focus_label in {"вопрос", "просьба"} and latest_outbound_short:
            return (
                "follow_up_after_self",
                "После твоего последнего короткого ответа исходный вопрос всё ещё выглядит не до конца закрытым.",
            )

        return (
            "hold",
            "После твоего последнего сообщения явного незакрытого повода писать ещё раз не видно.",
        )

    def _recency_bonus(self, age_from_end: int) -> float:
        if age_from_end <= 2:
            return 0.75 - (age_from_end * 0.05)
        if age_from_end <= 4:
            return 0.36
        if age_from_end <= 7:
            return 0.18
        return 0.06

    async def _resolve_person_memory(self, chat: Chat, message: Message):
        fallback_title = chat.title if chat.type == "private" else None
        fallback_handle = chat.handle if chat.type == "private" else None
        person_reference = build_person_reference(
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            fallback_title=fallback_title,
            fallback_handle=fallback_handle,
        )
        if person_reference is None:
            return None
        person_memory = await self.person_memory_repository.get_person_memory(
            person_reference.person_key
        )
        if person_memory is not None:
            return person_memory

        matches = await self.person_memory_repository.search_people_memory(
            person_reference.display_name,
            limit=1,
        )
        return matches[0] if matches else None

    async def _resolve_linked_people(self, chat_memory, person_memory):
        person_keys = [
            str(item.get("person_key"))
            for item in ((getattr(chat_memory, "linked_people_json", None) or []))
            if isinstance(item, dict) and item.get("person_key")
        ]
        linked_people = await self.person_memory_repository.get_people_memory_by_keys(person_keys)
        if person_memory is not None and all(
            item.person_key != person_memory.person_key for item in linked_people
        ):
            linked_people = [person_memory, *linked_people]
        return tuple(linked_people[:4])

    def _collect_topic_hints(
        self,
        *,
        target_message: Message,
        chat_memory,
        recent_messages: tuple[Message, ...],
    ) -> tuple[str, ...]:
        hints: list[str] = []
        for item in (getattr(chat_memory, "dominant_topics_json", None) or []):
            if isinstance(item, dict) and item.get("topic"):
                hints.append(str(item["topic"]).strip())

        recent_texts = [_pick_message_text(target_message)]
        recent_texts.extend(
            _pick_message_text(message)
            for message in recent_messages[-6:]
            if message.id != target_message.id
        )
        extracted_topics = extract_dominant_topics(
            [text for text in recent_texts if text],
            limit=3,
        )
        for topic in extracted_topics:
            label = str(topic.get("topic") or "").strip()
            if label:
                hints.append(label)

        unique_hints: list[str] = []
        seen: set[str] = set()
        for hint in hints:
            lowered = hint.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique_hints.append(truncate_text(hint, limit=40))
        return tuple(unique_hints[:3])


def _pick_message_text(message: Message) -> str:
    return " ".join((message.normalized_text or message.raw_text or "").split()).strip()


def _quote_focus_preview(message: Message) -> str:
    preview = truncate_text(_pick_message_text(message), limit=24)
    return f"«{preview}»"
