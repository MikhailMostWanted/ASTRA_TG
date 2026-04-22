from __future__ import annotations

from dataclasses import dataclass

from services.reply_examples_models import ReplyExamplesRetrievalResult
from services.reply_models import ReplyClassification, ReplyContext, ReplyDraft


@dataclass(slots=True)
class ReplyStrategyResolver:
    def resolve(
        self,
        *,
        context: ReplyContext,
        classification: ReplyClassification,
        few_shot_support: ReplyExamplesRetrievalResult | None = None,
    ) -> ReplyDraft:
        strategy, risk_label, base_confidence = self._choose_strategy(
            classification,
            few_shot_support=few_shot_support,
        )
        confidence = self._adjust_confidence(
            base_confidence=base_confidence,
            context=context,
            classification=classification,
            few_shot_support=few_shot_support,
        )
        reply_text = self._build_reply_text(
            context=context,
            classification=classification,
            strategy=strategy,
            few_shot_support=few_shot_support,
        )
        reason_short = self._build_reason_short(
            context=context,
            classification=classification,
            few_shot_support=few_shot_support,
        )
        source_preview = _format_source_preview(context.target_message)
        alternative_action = None
        if strategy == "не отвечать":
            alternative_action = (
                "Сначала дождись новой реплики или собери факты, потом вернись коротким спокойным сообщением."
            )

        return ReplyDraft(
            base_reply_text=reply_text,
            reason_short=reason_short,
            risk_label=risk_label,
            confidence=confidence,
            strategy=strategy,
            source_message_id=context.target_message.telegram_message_id,
            chat_id=context.chat.id,
            situation=classification.situation,
            source_message_preview=source_preview,
            focus_label=context.focus_label,
            focus_reason=context.focus_reason,
            few_shot_match_count=few_shot_support.match_count if few_shot_support else 0,
            few_shot_notes=few_shot_support.notes if few_shot_support else (),
            alternative_action=alternative_action,
        )

    def _choose_strategy(
        self,
        classification: ReplyClassification,
        *,
        few_shot_support: ReplyExamplesRetrievalResult | None,
    ) -> tuple[str, str, float]:
        if (
            few_shot_support is not None
            and few_shot_support.support_used
            and few_shot_support.strategy_bias == "clarify"
            and classification.situation in {"question", "soft_reply"}
        ):
            return "уточнить", "низкий", 0.76
        if classification.situation == "no_reply":
            return "не отвечать", "лучше не отвечать", 0.86
        if classification.situation == "tension":
            return "снять напряжение", "высокий", 0.64
        if classification.situation == "soft_reply":
            return "мягко ответить", "средний", 0.67
        if classification.situation == "request":
            return "мягко ответить", "средний", 0.74
        if classification.situation == "question":
            return "уточнить", "низкий", 0.72
        if classification.situation == "small_talk":
            return "поддержать", "низкий", 0.78
        return "мягко ответить", "средний", 0.62

    def _adjust_confidence(
        self,
        *,
        base_confidence: float,
        context: ReplyContext,
        classification: ReplyClassification,
        few_shot_support: ReplyExamplesRetrievalResult | None,
    ) -> float:
        confidence = base_confidence
        if context.has_memory_support:
            confidence += 0.06
        if len(context.recent_messages) >= 8:
            confidence += 0.04
        if not context.topic_hints:
            confidence -= 0.03
        if classification.has_tension:
            confidence -= 0.05
        if len(_pick_message_text(context.target_message)) <= 18:
            confidence -= 0.04
        if few_shot_support is not None and few_shot_support.support_used:
            confidence += few_shot_support.confidence_delta
        return max(0.35, min(round(confidence, 2), 0.95))

    def _build_reply_text(
        self,
        *,
        context: ReplyContext,
        classification: ReplyClassification,
        strategy: str,
        few_shot_support: ReplyExamplesRetrievalResult | None,
    ) -> str:
        topic_hint = classification.topic_hint
        if topic_hint is None and few_shot_support is not None:
            topic_hint = few_shot_support.dominant_topic_hint
        topic_chunk = _build_topic_chunk(topic_hint)
        short_mode = few_shot_support is not None and few_shot_support.length_hint == "short"
        strategy_bias = few_shot_support.strategy_bias if few_shot_support else None
        if strategy == "не отвечать":
            return (
                "Сейчас лучше не отвечать сразу. Тут нет явного запроса, "
                "а быстрый ответ только добавит шума."
            )
        if strategy == "снять напряжение":
            if strategy_bias == "promise_update":
                return (
                    f"Понял{topic_chunk}. Спокойно проверю детали и вернусь с коротким апдейтом "
                    "без лишней резкости."
                )
            return (
                f"Понял{topic_chunk}. Спокойно проверю детали и вернусь с конкретным апдейтом "
                "без лишних эмоций."
            )
        if strategy == "уточнить":
            if short_mode:
                return (
                    f"Понял{topic_chunk}. Что для тебя сейчас самое срочное? "
                    "Тогда отвечу точнее и без лишней воды."
                )
            return (
                f"Вижу вопрос{topic_chunk}. Уточни, пожалуйста, что для тебя сейчас самое срочное, "
                "и я отвечу точнее."
            )
        if strategy == "поддержать":
            return f"Да, понял{topic_chunk}. Я на связи, если нужно, продолжим отсюда."
        if strategy == "поставить границу":
            return (
                f"Вижу запрос{topic_chunk}. Давай без резкости: я отвечу по делу, "
                "как только проверю детали."
            )
        if classification.has_request or classification.has_question:
            if strategy_bias == "promise_update":
                return (
                    f"Понял{topic_chunk}. Смотрю это сейчас и вернусь с коротким апдейтом "
                    "чуть позже."
                )
            return (
                f"Понял{topic_chunk}. Смотрю это сейчас и вернусь с конкретным апдейтом чуть позже."
            )
        if short_mode:
            return f"Понял{topic_chunk}. Посмотрю и коротко вернусь."
        return f"Понял{topic_chunk}. Я это посмотрю и коротко вернусь с ответом."

    def _build_reason_short(
        self,
        *,
        context: ReplyContext,
        classification: ReplyClassification,
        few_shot_support: ReplyExamplesRetrievalResult | None,
    ) -> str:
        parts = [classification.reason]
        if context.pending_loops:
            parts.append("В памяти чата уже есть открытый хвост по этой теме.")
        if context.person_memory is not None and getattr(
            context.person_memory,
            "interaction_pattern",
            None,
        ):
            parts.append("Память по человеку подсказывает держать ответ коротким и спокойным.")
        if few_shot_support is not None and few_shot_support.support_used:
            parts.append(few_shot_support.notes[0])
        return " ".join(parts[:3])


def _build_topic_chunk(topic_hint: str | None) -> str:
    if not topic_hint:
        return ""
    return f" про {topic_hint}"


def _format_source_preview(message) -> str:
    sender = message.sender_name or "без имени"
    return f"{sender}: {_pick_message_text(message)}"


def _pick_message_text(message) -> str:
    return " ".join((message.normalized_text or message.raw_text or "").split()).strip()
