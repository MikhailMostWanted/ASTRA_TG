from __future__ import annotations

from services.digest_builder import DigestBuildResult
from services.persona_core import PersonaState
from services.providers.models import (
    DigestImproveRequest,
    ProviderPrompt,
    ProviderTask,
    RewriteReplyRequest,
)


MAX_CONTEXT_MESSAGES = 6


def build_reply_refine_request(
    *,
    context,
    baseline_messages: tuple[str, ...],
    style_selection,
    persona_state: PersonaState,
    few_shot_support=None,
    classification=None,
) -> RewriteReplyRequest:
    recent_messages = tuple(context.working_messages[-MAX_CONTEXT_MESSAGES:])
    context_lines = [
        f"Чат: {context.chat.title}",
        f"Фокус: {context.focus_label}",
        f"Последнее входящее: {context.target_message.sender_name or 'собеседник'}: {context.target_message.normalized_text or context.target_message.raw_text}",
        f"Почему сейчас: {context.reply_opportunity_reason}",
    ]
    if classification is not None:
        context_lines.append(f"Ситуация: {classification.situation}")
    if context.chat_memory and context.chat_memory.current_state:
        context_lines.append(f"Текущее состояние: {context.chat_memory.current_state}")
    if context.pending_loops:
        context_lines.append("Открытые хвосты: " + "; ".join(context.pending_loops[:2]))
    if context.unanswered_questions:
        context_lines.append("Незакрытые вопросы: " + "; ".join(context.unanswered_questions[:2]))
    if context.pending_promises:
        context_lines.append("Твои обещания/апдейты: " + "; ".join(context.pending_promises[:2]))
    if context.emotional_signals:
        context_lines.append("Эмоциональные сигналы: " + "; ".join(context.emotional_signals[:2]))
    if context.local_dynamics:
        context_lines.append("Динамика: " + "; ".join(context.local_dynamics[:2]))
    if context.person_memory and context.person_memory.interaction_pattern:
        context_lines.append(
            "Паттерн контакта: " + context.person_memory.interaction_pattern
        )

    recent_lines = [
        f"- {message.sender_name or 'участник'}: {message.normalized_text or message.raw_text}"
        for message in recent_messages
        if (message.normalized_text or message.raw_text)
    ]
    baseline_lines = [f"- {message}" for message in baseline_messages]
    retrieval_lines = _collect_reply_examples(few_shot_support)
    persona_constraints = _collect_persona_constraints(persona_state)
    style_constraints = _collect_style_constraints(style_selection.profile)

    user_input = "\n".join(
        [
            "Контекст:",
            *context_lines,
            "",
            "Последние сообщения:",
            *(recent_lines or ["- нет"]),
            "",
            "Базовый вариант:",
            *baseline_lines,
            "",
            "Похожие реальные ответы:",
            *(retrieval_lines or ["- нет"]),
            "",
            "Ограничения стиля:",
            *style_constraints,
            "",
            "Persona constraints:",
            *persona_constraints,
        ]
    )
    system_instructions = (
        "Ты пишешь живой ответ в обычном Telegram-чате от лица владельца аккаунта. "
        "Не играй ассистента. Никакого канцелярита, литературщины, markdown и пояснений. "
        "Опирайся только на контекст, открытые хвосты и стиль из примеров. "
        "Не придумывай новые факты, сроки, числа, имена, обещания, ссылки или @username. "
        "Верни только JSON-объект вида "
        "{\"primary\": [str], \"short\": [str], \"soft\": [str], \"style\": [str]}. "
        "В каждом поле 1-4 коротких телеграм-сообщения. "
        "\"primary\" — лучший вариант, \"short\" — заметно короче, \"soft\" — мягче, "
        "\"style\" — в более разговорной и каскадной манере владельца."
    )
    allowed_context = tuple(context_lines + recent_lines + baseline_lines)
    return RewriteReplyRequest(
        prompt=ProviderPrompt(
            task=ProviderTask.REWRITE_REPLY,
            system_instructions=system_instructions,
            user_input=user_input,
            response_format="json",
        ),
        baseline_messages=baseline_messages,
        allowed_context=allowed_context,
    )


def build_digest_improve_request(
    *,
    build_result: DigestBuildResult,
) -> DigestImproveRequest:
    summary_lines = [
        "Текущий детерминированный дайджест:",
        f"summary_short: {build_result.summary_short}",
        "",
        "overview_lines:",
        *build_result.overview_lines,
        "",
        "key_source_lines:",
        *build_result.key_source_lines,
        "",
        "source_titles:",
        *[f"- {source.display_title}" for source in build_result.source_summaries],
    ]
    system_instructions = (
        "Ты улучшаешь формулировки детерминированного дайджеста, но не меняешь факты. "
        "Нельзя придумывать новые события, числа, сроки, источники или выводы. "
        "Сохрани source titles буквально. "
        "Верни только JSON-объект вида "
        "{\"summary_short\": str, \"overview_lines\": [str], \"key_source_lines\": [str]}."
    )
    return DigestImproveRequest(
        prompt=ProviderPrompt(
            task=ProviderTask.IMPROVE_DIGEST,
            system_instructions=system_instructions,
            user_input="\n".join(summary_lines),
            response_format="json",
        ),
        baseline_summary_short=build_result.summary_short,
        baseline_overview_lines=tuple(build_result.overview_lines),
        baseline_key_source_lines=tuple(build_result.key_source_lines),
        source_titles=tuple(source.display_title for source in build_result.source_summaries),
    )


def _collect_style_constraints(profile) -> tuple[str, ...]:
    return (
        f"- profile_key: {profile.key}",
        f"- target_message_count: {profile.target_message_count}",
        f"- max_message_count: {profile.max_message_count}",
        f"- avg_length_hint: {profile.avg_length_hint}",
        f"- punctuation_level: {profile.punctuation_level}",
        f"- casing_mode: {profile.casing_mode}",
        f"- rhythm_mode: {profile.rhythm_mode}",
        (
            "- preferred_openers: " + ", ".join(profile.preferred_openers)
            if profile.preferred_openers
            else "- preferred_openers: нет"
        ),
        (
            "- avoid_patterns: " + ", ".join(profile.avoid_patterns)
            if profile.avoid_patterns
            else "- avoid_patterns: нет"
        ),
    )


def _collect_persona_constraints(persona_state: PersonaState) -> tuple[str, ...]:
    if not persona_state.enabled or persona_state.core is None:
        return ("- persona слой не активен, просто не уезжай в бота.",)
    core = persona_state.core
    anti_patterns = ", ".join(core.anti_pattern_rules[:4]) or "нет"
    speech_rules = ", ".join(core.core_speech_rules[:4]) or "нет"
    return (
        f"- speech_rules: {speech_rules}",
        f"- anti_patterns: {anti_patterns}",
        (
            "- rewrite_constraints: " + ", ".join(core.rewrite_constraints)
            if core.rewrite_constraints
            else "- rewrite_constraints: нет"
        ),
    )


def _collect_reply_examples(few_shot_support) -> tuple[str, ...]:
    if few_shot_support is None or not few_shot_support.support_used:
        return ()
    lines: list[str] = []
    for index, match in enumerate(few_shot_support.matches[:3], start=1):
        lines.append(
            f"- пример {index}: входящее={match.inbound_text} | реальный ответ={match.outbound_text}"
        )
    return tuple(lines)
