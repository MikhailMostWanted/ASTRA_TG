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
        focus_label, focus_reason = self._apply_decision_consistency(
            context=context,
            strategy=strategy,
        )
        source_preview = _format_source_preview(context.target_message)
        alternative_action = None
        if strategy == "не отвечать":
            reason_parts: list[str] = []
            for part in (reason_short, context.reply_opportunity_reason):
                if not part or part in reason_parts:
                    continue
                reason_parts.append(part)
            reason_short = " ".join(reason_parts)
            alternative_action = (
                "Сначала дождись новой реплики или собери факты, потом вернись коротким спокойным сообщением."
            )

        return ReplyDraft(
            base_reply_text=reply_text,
            reason_short=reason_short,
            risk_label=risk_label,
            confidence=confidence,
            strategy=strategy,
            source_message_id=context.target_local_message_id,
            chat_id=context.chat.id,
            situation=classification.situation,
            source_message_preview=source_preview,
            focus_label=focus_label,
            focus_reason=focus_reason,
            focus_score=context.focus_score,
            selection_message_count=context.selection_message_count,
            source_message_key=context.target_message_key,
            source_local_message_id=context.target_local_message_id,
            source_runtime_message_id=context.target_runtime_message_id,
            source_backend=context.workspace_source,
            few_shot_match_count=few_shot_support.match_count if few_shot_support else 0,
            few_shot_notes=few_shot_support.notes if few_shot_support else (),
            few_shot_matches=few_shot_support.matches if few_shot_support else (),
            few_shot_strategy_bias=few_shot_support.strategy_bias if few_shot_support else None,
            few_shot_length_hint=few_shot_support.length_hint if few_shot_support else None,
            few_shot_rhythm_hint=few_shot_support.rhythm_hint if few_shot_support else None,
            few_shot_dominant_topic_hint=(
                few_shot_support.dominant_topic_hint if few_shot_support else None
            ),
            few_shot_message_count_hint=(
                few_shot_support.message_count_hint if few_shot_support else None
            ),
            few_shot_style_markers=(
                few_shot_support.style_markers if few_shot_support else ()
            ),
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
        follow_up_after_self = context.reply_opportunity_mode == "follow_up_after_self"
        contextual_reply = _build_contextual_short_reply(context)
        if contextual_reply is not None and strategy != "не отвечать":
            return contextual_reply
        if strategy == "не отвечать":
            return (
                "Сейчас лучше не писать. Явного повода нет, а лишний follow-up тут только собьёт темп."
            )
        if follow_up_after_self:
            if strategy == "снять напряжение":
                return (
                    f"Не пропал{topic_chunk}. Хвост держу в работе, вернусь коротко и спокойно."
                )
            if strategy == "уточнить":
                if short_mode:
                    return (
                        f"Чтобы не потерять хвост{topic_chunk}, уточню одно: что сейчас важнее всего?"
                    )
                return (
                    f"Чтобы не потерять хвост{topic_chunk}, уточни одно: что сейчас важнее всего? "
                    "Тогда вернусь точнее."
                )
            if strategy == "поддержать":
                return (
                    f"По теме{topic_chunk} я в контексте. Если нужен отдельный follow-up, добью его коротко."
                )
            if strategy_bias == "promise_update":
                return (
                    f"По теме{topic_chunk} хвост у меня в работе. Если приоритет сдвинулся, дай знак."
                )
            return (
                f"По теме{topic_chunk} хвост у меня в работе. Если нужен отдельный follow-up, вернусь коротко."
            )
        if strategy == "снять напряжение":
            if strategy_bias == "promise_update":
                return (
                    f"Понял{topic_chunk}. Спокойно гляну и вернусь коротким апдейтом."
                )
            return (
                f"Понял{topic_chunk}. Спокойно гляну детали и вернусь коротко."
            )
        if strategy == "уточнить":
            if short_mode:
                return (
                    f"Понял{topic_chunk}. Что сейчас важнее всего? Тогда отвечу точнее."
                )
            return (
                f"Тут вопрос{topic_chunk}. Уточни одно: что сейчас важнее всего? Тогда отвечу точнее."
            )
        if strategy == "поддержать":
            return f"Да, понял{topic_chunk}. Если что, продолжим отсюда."
        if strategy == "поставить границу":
            return (
                f"Тут запрос{topic_chunk}. Давай спокойно: отвечу по делу, как только гляну детали."
            )
        if classification.has_request or classification.has_question:
            if strategy_bias == "promise_update":
                return (
                    f"Понял{topic_chunk}. Смотрю это сейчас и вернусь с апдейтом."
                )
            if short_mode:
                return f"Понял{topic_chunk}. Гляну и вернусь."
            return f"Понял{topic_chunk}. Гляну и вернусь с ответом."
        if short_mode:
            return f"Понял{topic_chunk}. Гляну и вернусь."
        return f"Понял{topic_chunk}. Гляну и коротко вернусь."

    def _build_reason_short(
        self,
        *,
        context: ReplyContext,
        classification: ReplyClassification,
        few_shot_support: ReplyExamplesRetrievalResult | None,
    ) -> str:
        parts = [classification.reason]
        if context.reply_opportunity_mode == "follow_up_after_self":
            parts.append(context.reply_opportunity_reason)
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

    def _apply_decision_consistency(
        self,
        *,
        context: ReplyContext,
        strategy: str,
    ) -> tuple[str, str]:
        if strategy != "не отвечать":
            return context.focus_label, context.focus_reason
        if context.focus_label != "продолжение темы":
            return context.focus_label, context.focus_reason
        return (
            "слабый триггер",
            (
                "В свежем окне не видно явного вопроса, просьбы или сильного незакрытого хвоста. "
                f"{context.reply_opportunity_reason}"
            ),
        )


def _build_topic_chunk(topic_hint: str | None) -> str:
    if not topic_hint:
        return ""
    return f" про {topic_hint}"


def _format_source_preview(message) -> str:
    sender = message.sender_name or "без имени"
    cleaned_text = _strip_sender_prefix(_pick_message_text(message), sender)
    return f"{sender}: {cleaned_text}" if cleaned_text else sender


def _pick_message_text(message) -> str:
    return " ".join((message.normalized_text or message.raw_text or "").split()).strip()


def _strip_sender_prefix(text: str, sender: str) -> str:
    cleaned = " ".join(text.split()).strip()
    normalized_sender = " ".join(str(sender).split()).strip()
    if not cleaned or not normalized_sender:
        return cleaned

    prefixes = tuple(f"{normalized_sender}{delimiter}" for delimiter in (":", "-", "—", "–"))
    while cleaned:
        lowered = cleaned.casefold()
        matched_prefix = next(
            (prefix for prefix in prefixes if lowered.startswith(prefix.casefold())),
            None,
        )
        if matched_prefix is None:
            break
        cleaned = cleaned[len(matched_prefix) :].lstrip(" :—–-\t")
    return cleaned


def _build_contextual_short_reply(context: ReplyContext) -> str | None:
    recent_inbound = [
        _pick_message_text(message)
        for message in context.working_messages[-6:]
        if message.direction == "inbound" and _pick_message_text(message)
    ]
    tail = " ".join(recent_inbound).casefold()
    if not tail:
        return None

    excludes_person = any(
        marker in tail
        for marker in (
            "не относится к нам",
            "не относится",
            "не к нам",
            "вообще мимо",
        )
    )
    protocol_context = "от протокола" in tail or "протокол" in tail
    mentions_sanya = "саня" in tail or "саню" in tail or "сани" in tail
    if excludes_person and protocol_context:
        if mentions_sanya:
            return "а ну тогда саню можно не считать"
        return "а ну тогда его не трогаем"
    if excludes_person:
        return "а ну тогда он вообще мимо"
    return None
