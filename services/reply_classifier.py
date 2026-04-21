from __future__ import annotations

from dataclasses import dataclass

from services.memory_common import looks_like_conflict, normalize_display_name
from services.reply_models import ReplyClassification, ReplyContext


QUESTION_WORDS = (
    "когда",
    "где",
    "что",
    "как",
    "почему",
    "зачем",
    "сколько",
    "какой",
    "какая",
    "какие",
    "можно",
    "сможешь",
    "успеешь",
)
REQUEST_MARKERS = (
    "посмотри",
    "скинь",
    "пришли",
    "сделай",
    "проверь",
    "дай",
    "напомни",
    "подскажи",
    "возьми",
    "подготовь",
    "нужно",
    "надо",
    "давай",
)
NO_REPLY_MARKERS = {
    "ок",
    "окей",
    "ага",
    "ясно",
    "понял",
    "поняла",
    "спасибо",
    "спс",
    "принято",
    "хорошо",
    "понятно",
}
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

        return self.classify_text(
            text=text,
            chat_state=chat_state,
            interaction_pattern=interaction_pattern,
            has_open_loops=has_open_loops,
            topic_hint=topic_hint,
        )

    def classify_text(
        self,
        *,
        text: str,
        chat_state: str,
        interaction_pattern: str,
        has_open_loops: bool,
        topic_hint: str | None = None,
    ) -> ReplyClassification:
        normalized = " ".join(text.split()).strip()
        lowered = normalized.casefold()
        tokens = tuple(token.strip(".,!?():;\"'«»") for token in lowered.split())

        has_question = "?" in normalized or any(token in QUESTION_WORDS for token in tokens)
        has_request = any(marker in lowered for marker in REQUEST_MARKERS)
        has_tension = looks_like_conflict(normalized) or "напряж" in chat_state.casefold()
        is_short_ack = normalized and len(tokens) <= 3 and all(token in NO_REPLY_MARKERS for token in tokens)
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
                reason="Вижу напряжённый тон или жалобу, поэтому лучше отвечать спокойно и без встречной резкости.",
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
                reason="Сообщение лучше закрывать мягко и предметно, чтобы не разогнать лишнюю резкость.",
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
                reason="Последнее сообщение выглядит как вопрос или уточнение, поэтому безопаснее ответить коротко и по делу.",
                has_question=True,
                has_request=has_request,
                has_tension=has_tension,
                should_reply=True,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        if has_request or has_open_loops:
            return ReplyClassification(
                situation="request",
                reason="Похоже на просьбу или ожидание действия, поэтому лучше подтвердить, что тема взята в работу.",
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
                reason="Последнее сообщение выглядит как вопрос или уточнение, поэтому безопаснее ответить коротко и по делу.",
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
                reason="Это короткая бытовая реплика без явного риска, тут достаточно живого короткого ответа.",
                has_question=False,
                has_request=False,
                has_tension=False,
                should_reply=True,
                needs_softness=False,
                topic_hint=topic_hint,
            )

        return ReplyClassification(
            situation="soft_reply",
            reason="Контекст остаётся немного неопределённым, поэтому безопаснее короткий нейтральный ответ.",
            has_question=False,
            has_request=False,
            has_tension=False,
            should_reply=True,
            needs_softness=False,
            topic_hint=topic_hint,
        )


def _pick_message_text(message) -> str:
    return normalize_display_name(message.normalized_text or message.raw_text or "") or ""
