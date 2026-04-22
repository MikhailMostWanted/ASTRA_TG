from __future__ import annotations

from dataclasses import dataclass

from services.memory_common import normalize_display_name
from services.reply_models import ReplyClassification, ReplyContext
from services.reply_signal import (
    has_emotional_signal,
    has_open_loop_signal,
    has_question_signal,
    has_request_signal,
    is_low_signal_text,
    reply_tokens,
)


SMALL_TALK_MARKERS = (
    "привет",
    "доброе",
    "спасибо",
    "спс",
    "супер",
    "класс",
    "ок",
    "окей",
)
SOFT_REPLY_MARKERS = (
    "почему",
    "опять",
    "где",
    "игнор",
    "жду",
    "срочно",
    "не устраивает",
    "непонятно",
)


@dataclass(slots=True)
class ReplyClassifier:
    def classify(self, context: ReplyContext) -> ReplyClassification:
        text = _pick_message_text(context.target_message)
        has_open_loops = bool(
            context.pending_loops
            or (getattr(context.person_memory, "open_loops_json", None) or [])
            or context.reply_opportunity_mode == "follow_up_after_self"
        )
        interaction_pattern = (
            getattr(context.person_memory, "interaction_pattern", None) or ""
        )
        chat_state = getattr(context.chat_memory, "current_state", None) or ""
        topic_hint = context.topic_hints[0] if context.topic_hints else None

        if context.chat.type == "channel":
            return ReplyClassification(
                situation="no_reply",
                reason="Это канал без живого диалога, поэтому безопаснее не предлагать искусственный ответ.",
                has_question=False,
                has_request=False,
                has_tension=False,
                should_reply=False,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        if (
            context.latest_message.direction == "outbound"
            and context.reply_opportunity_mode != "follow_up_after_self"
        ):
            return ReplyClassification(
                situation="no_reply",
                reason=context.reply_opportunity_reason,
                has_question=False,
                has_request=False,
                has_tension=False,
                should_reply=False,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        return self.classify_text(
            text=text,
            chat_state=chat_state,
            interaction_pattern=interaction_pattern,
            has_open_loops=has_open_loops,
            topic_hint=topic_hint,
            follow_up_after_self=context.reply_opportunity_mode == "follow_up_after_self",
        )

    def classify_text(
        self,
        *,
        text: str,
        chat_state: str,
        interaction_pattern: str,
        has_open_loops: bool,
        topic_hint: str | None = None,
        follow_up_after_self: bool = False,
    ) -> ReplyClassification:
        normalized = " ".join(text.split()).strip()
        lowered = normalized.casefold()
        tokens = reply_tokens(lowered)

        has_question = has_question_signal(normalized)
        has_request = has_request_signal(normalized)
        has_open_loop_signal_text = has_open_loop_signal(normalized)
        has_tension = has_emotional_signal(normalized) or "напряж" in chat_state.casefold()
        is_short_ack = is_low_signal_text(normalized)
        has_small_talk = len(normalized) <= 48 and any(marker in lowered for marker in SMALL_TALK_MARKERS)
        needs_softness = has_tension or any(marker in lowered for marker in SOFT_REPLY_MARKERS)
        mentions_sensitive_pattern = "часто задаёт вопросы" in interaction_pattern.casefold()

        if is_short_ack:
            return ReplyClassification(
                situation="no_reply",
                reason="Явного запроса нет, а быстрый ответ сейчас скорее создаст лишний шум.",
                has_question=False,
                has_request=False,
                has_tension=False,
                should_reply=False,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        if has_tension and ("!" in normalized or "срочно" in lowered or "почему" in lowered):
            return ReplyClassification(
                situation="tension",
                reason=(
                    "Несмотря на последнее исходящее, в теме осталось напряжение, поэтому лучше вернуться спокойно и без встречной резкости."
                    if follow_up_after_self
                    else "Фокус ответа звучит напряжённо, поэтому лучше отвечать спокойно и без встречной резкости."
                ),
                has_question=has_question,
                has_request=has_request,
                has_tension=True,
                should_reply=True,
                needs_softness=True,
                topic_hint=topic_hint,
            )

        if needs_softness:
            return ReplyClassification(
                situation="soft_reply",
                reason=(
                    "После твоего последнего сообщения тема всё ещё просится в мягкий follow-up, чтобы не разогнать лишнюю резкость."
                    if follow_up_after_self
                    else "Фокус ответа лучше закрывать мягко и предметно, чтобы не разогнать лишнюю резкость."
                ),
                has_question=has_question,
                has_request=has_request,
                has_tension=has_tension,
                should_reply=True,
                needs_softness=True,
                topic_hint=topic_hint,
            )

        if has_question:
            return ReplyClassification(
                situation="question",
                reason=(
                    "Несмотря на последнее исходящее, вопрос по фокусу всё ещё выглядит незакрытым, поэтому уместен короткий follow-up."
                    if follow_up_after_self
                    else "Фокус ответа выглядит как вопрос или уточнение, поэтому безопаснее ответить коротко и по делу."
                ),
                has_question=True,
                has_request=has_request,
                has_tension=has_tension,
                should_reply=True,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        if has_request or has_open_loops or has_open_loop_signal_text:
            return ReplyClassification(
                situation="request",
                reason=(
                    "После твоего последнего сообщения по фокусу всё ещё висит ожидание действия, поэтому можно вернуться коротким follow-up."
                    if follow_up_after_self
                    else "Фокус ответа похож на просьбу или ожидание действия, поэтому лучше подтвердить, что тема взята в работу."
                ),
                has_question=has_question,
                has_request=True,
                has_tension=has_tension,
                should_reply=True,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        if mentions_sensitive_pattern:
            return ReplyClassification(
                situation="question",
                reason="Фокус ответа выглядит как вопрос или уточнение, поэтому безопаснее ответить коротко и по делу.",
                has_question=True,
                has_request=has_request,
                has_tension=has_tension,
                should_reply=True,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        if has_small_talk:
            return ReplyClassification(
                situation="small_talk",
                reason="Фокус ответа выглядит как короткая бытовая реплика без явного риска, тут достаточно живого короткого ответа.",
                has_question=False,
                has_request=False,
                has_tension=False,
                should_reply=True,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        return ReplyClassification(
            situation="soft_reply",
            reason="Контекст вокруг выбранного фокуса остаётся немного неопределённым, поэтому безопаснее короткий нейтральный ответ.",
            has_question=False,
            has_request=False,
            has_tension=False,
            should_reply=True,
            needs_softness=False,
            topic_hint=topic_hint,
        )


def _pick_message_text(message) -> str:
    return normalize_display_name(message.normalized_text or message.raw_text or "") or ""
