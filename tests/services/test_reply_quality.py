from types import SimpleNamespace

import pytest

from services.persona_core import PersonaState
from services.persona_rules import OwnerPersonaCore, PersonaGuardrailConfig
from services.providers.guardrails import ReplyRefinementGuardrails
from services.providers.models import ReplyRefinementCandidate
from services.reply_postprocessor import postprocess_variant_messages
from services.reply_variants import ReplyVariantBuilder
from services.style_adapter import StyleAdapter
from services.style_profiles import StyleProfileSnapshot


FORBIDDEN_READY_TEXT = (
    "я бы ответил",
    "можно написать",
    "вариант ответа",
    "предлагаю ответить",
)


def test_owner_style_variant_is_short_cascade_without_assistant_tone() -> None:
    variants = ReplyVariantBuilder().build(
        final_messages=(
            "**Я бы ответил так:** Понял, сейчас спокойно посмотрю задачу, разберусь что там происходит и вернусь с нормальным ответом.",
        ),
        few_shot_support=SimpleNamespace(opener_hint="не не", rhythm_hint="series"),
    )

    owner_style = next(variant for variant in variants if variant.id == "owner_style")
    lines = owner_style.text.splitlines()

    assert 2 <= len(lines) <= 4
    assert all(1 <= len(line.split()) <= 9 for line in lines)
    assert "**" not in owner_style.text
    assert not any(pattern in owner_style.text.casefold() for pattern in FORBIDDEN_READY_TEXT)


def test_short_and_soft_variants_have_real_tone_differences() -> None:
    variants = ReplyVariantBuilder().build(
        final_messages=("да бля я понял, это хуйня какая то, щас гляну и вернусь нормально",),
        few_shot_support=SimpleNamespace(opener_hint="да", rhythm_hint="series"),
    )
    by_id = {variant.id: variant.text for variant in variants}

    assert len(by_id["short"]) < len(by_id["primary"])
    assert "бля" not in by_id["soft"].casefold()
    assert "хуйня" not in by_id["soft"].casefold()
    assert by_id["soft"] != by_id["primary"]


def test_retrieval_hints_change_opener_rhythm_and_length() -> None:
    profile = _owner_profile()
    adapted = StyleAdapter().adapt(
        draft_text="Понял. Сейчас посмотрю задачу и вернусь с нормальным ответом.",
        profile=profile,
        strategy="мягко ответить",
        few_shot_support=SimpleNamespace(
            opener_hint="да",
            rhythm_hint="series",
            length_hint="short",
            message_count_hint=3,
        ),
    )

    assert adapted.messages[0].startswith("да ")
    assert len(adapted.messages) >= 2
    assert all(len(message.split()) <= 8 for message in adapted.messages)


def test_postprocessing_breaks_long_owner_style_into_short_lines() -> None:
    messages = postprocess_variant_messages(
        (
            "Не не я не про это я просто щас пытаюсь понять что именно ты имеешь в виду и почему оно так поехало",
        ),
        variant_id="owner_style",
        opener_hint="не не",
    )

    assert 2 <= len(messages) <= 4
    assert all(len(message.split()) <= 9 for message in messages)


def test_guardrails_accept_normal_conversational_owner_style() -> None:
    decision = ReplyRefinementGuardrails().apply(
        candidate=ReplyRefinementCandidate(
            messages=("да бля я понял", "щас гляну"),
            raw_text="да бля я понял\nщас гляну",
        ),
        baseline_messages=("да понял", "гляну"),
        allowed_context=("Саша: глянь задачу", "да понял", "гляну"),
        profile=_owner_profile(),
        persona_state=_persona_state(),
    )

    assert decision.used_fallback is False
    assert decision.messages == ("да бля я понял", "щас гляну")


@pytest.mark.parametrize(
    ("candidate", "expected_flag"),
    [
        ("да, завтра утром отправлю файл", "новые_факты"),
        ("Я бы ответил так: да понял, сейчас посмотрю", "assistant_tone"),
        (" ".join(["очень подробно"] * 36), "слишком_длинная_простыня"),
        ("иди нахуй, я не буду это смотреть", "токсичность"),
    ],
)
def test_guardrails_reject_bad_reply_candidates(candidate: str, expected_flag: str) -> None:
    decision = ReplyRefinementGuardrails().apply(
        candidate=ReplyRefinementCandidate(messages=(candidate,), raw_text=candidate),
        baseline_messages=("да понял", "гляну"),
        allowed_context=("Саша: глянь задачу", "да понял", "гляну"),
        profile=_owner_profile(),
        persona_state=_persona_state(),
    )

    assert decision.used_fallback is True
    assert expected_flag in decision.flags
    assert decision.messages == ("да понял", "гляну")


def _owner_profile() -> StyleProfileSnapshot:
    return StyleProfileSnapshot(
        id=7,
        key="owner_style",
        title="Мой стиль",
        description="Тестовый owner style",
        sort_order=5,
        message_mode="series",
        target_message_count=3,
        max_message_count=4,
        avg_length_hint="short",
        punctuation_level="low",
        profanity_level="functional",
        warmth_level="medium",
        directness_level="high",
        explanation_pattern=("коротко",),
        preferred_openers=("ну", "да", "не", "не не", "а", "щас"),
        preferred_closers=("если что скажу",),
        avoid_patterns=("я бы ответил", "можно написать", "вариант ответа"),
        casing_mode="mostly_lower",
        rhythm_mode="telegram_cascade",
    )


def _persona_state() -> PersonaState:
    return PersonaState(
        enabled=True,
        version="owner-core-v1",
        core=OwnerPersonaCore.from_payload(
            {
                "core_speech_rules": ["коротко", "каскадом"],
                "explanation_pattern": ["сузить смысл"],
                "warmth_rules": ["без сахара"],
                "directness_rules": ["прямо"],
                "profanity_rules": ["мат только если уместно"],
                "anti_pattern_rules": ["нельзя звучать как ассистент"],
                "opener_bank": ["ну", "да", "не", "не не", "а", "щас"],
                "closer_bank": ["если что скажу"],
                "rewrite_constraints": ["mostly_lower", "low_punctuation"],
            }
        ),
        guardrails=PersonaGuardrailConfig.from_payload(
            {
                "checks": ["message_count", "average_length", "bot_phrases", "profanity_overuse"],
                "max_messages": 4,
                "max_message_length": 90,
                "max_average_message_length": 60,
                "max_exclamation_count": 1,
                "max_periods_per_message": 1,
                "max_repeated_openers": 1,
                "max_strong_profane_tokens": 1,
                "literary_patterns": ["в данном случае", "благодарю"],
                "bot_patterns": ["я бы ответил", "можно написать", "предлагаю ответить"],
                "forbidden_patterns": ["!!!"],
            }
        ),
        source="tests",
    )
