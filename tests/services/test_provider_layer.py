import asyncio

from config.settings import Settings
from services.persona_core import PersonaState
from services.persona_rules import OwnerPersonaCore, PersonaGuardrailConfig
from services.providers.guardrails import ReplyRefinementGuardrails
from services.providers.manager import ProviderManager
from services.providers.models import ReplyRefinementCandidate
from services.style_profiles import StyleProfileSnapshot


def test_provider_manager_reports_disabled_mode(monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    manager = ProviderManager.from_settings(Settings())
    status = asyncio.run(manager.get_status())

    assert status.enabled is False
    assert status.configured is False
    assert status.provider_name is None
    assert status.available is False
    assert status.reply_refine_available is False
    assert status.digest_refine_available is False
    assert "выключ" in status.reason.lower()


def test_provider_manager_accepts_optional_api_key_for_openai_compatible_provider(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL_FAST", "test-fast")
    monkeypatch.setenv("LLM_MODEL_DEEP", "test-deep")
    monkeypatch.setenv("LLM_REFINE_REPLY_ENABLED", "true")
    monkeypatch.setenv("LLM_REFINE_DIGEST_ENABLED", "true")

    manager = ProviderManager.from_settings(Settings())
    status = asyncio.run(manager.get_status())

    assert status.enabled is True
    assert status.configured is True
    assert status.available is True
    assert status.reply_refine_available is True
    assert status.digest_refine_available is True
    assert "сконфигурирован" in status.reason.lower()


def test_reply_refinement_guardrails_accept_good_candidate() -> None:
    guardrails = ReplyRefinementGuardrails()
    profile = _build_profile()
    persona_state = _build_persona_state()
    baseline = ("ну давай я к вечеру добью файл", "если что отдельно пну")
    candidate = ReplyRefinementCandidate(
        messages=("ну давай к вечеру добью файл", "если что отдельно пну"),
        raw_text="ну давай к вечеру добью файл\nесли что отдельно пну",
        model_name="test-fast",
    )

    decision = guardrails.apply(
        candidate=candidate,
        baseline_messages=baseline,
        allowed_context=(
            "Анна ждёт финальный файл по бюджету.",
            "Когда сможешь скинуть финальный файл по бюджету?",
        ),
        profile=profile,
        persona_state=persona_state,
    )

    assert decision.used_fallback is False
    assert decision.messages == candidate.messages
    assert decision.flags == ()


def test_reply_refinement_guardrails_accepts_contextual_candidate_even_if_baseline_is_thin() -> None:
    guardrails = ReplyRefinementGuardrails()
    profile = _build_profile()
    persona_state = _build_persona_state()
    baseline = ("понял",)
    candidate = ReplyRefinementCandidate(
        messages=(
            "Понял. Проверю файл по бюджету и к вечеру вернусь коротким апдейтом.",
        ),
        raw_text="Понял. Проверю файл по бюджету и к вечеру вернусь коротким апдейтом.",
        model_name="test-fast",
    )

    decision = guardrails.apply(
        candidate=candidate,
        baseline_messages=baseline,
        allowed_context=(
            "Анна ждёт финальный файл по бюджету.",
            "Когда сможешь скинуть финальный файл по бюджету?",
        ),
        profile=profile,
        persona_state=persona_state,
    )

    assert decision.used_fallback is False
    assert decision.messages == candidate.messages
    assert "слишком_длинно" not in decision.flags
    assert "сильное_отклонение_от_baseline" not in decision.flags


def test_reply_refinement_guardrails_reject_bad_candidate_and_fallback() -> None:
    guardrails = ReplyRefinementGuardrails()
    profile = _build_profile()
    persona_state = _build_persona_state()
    baseline = ("ну давай я к вечеру добью файл", "если что отдельно пну")
    candidate = ReplyRefinementCandidate(
        messages=(
            "В данном случае благодарю за терпение, я подготовлю развёрнутый файл с бюджетом на 25 страниц уже завтра утром!!!",
        ),
        raw_text="В данном случае благодарю за терпение, я подготовлю развёрнутый файл с бюджетом на 25 страниц уже завтра утром!!!",
        model_name="test-fast",
    )

    decision = guardrails.apply(
        candidate=candidate,
        baseline_messages=baseline,
        allowed_context=(
            "Анна ждёт финальный файл по бюджету.",
            "Когда сможешь скинуть финальный файл по бюджету?",
        ),
        profile=profile,
        persona_state=persona_state,
    )

    assert decision.used_fallback is True
    assert decision.messages == baseline
    assert "слишком_литературно" in decision.flags


def test_reply_refinement_guardrails_still_reject_obvious_off_topic_candidate() -> None:
    guardrails = ReplyRefinementGuardrails()
    profile = _build_profile()
    persona_state = _build_persona_state()
    baseline = ("ну давай я к вечеру добью файл", "если что отдельно пну")
    candidate = ReplyRefinementCandidate(
        messages=("Давай вечером созвонимся про отпуск и билеты, там добьём отдельно.",),
        raw_text="Давай вечером созвонимся про отпуск и билеты, там добьём отдельно.",
        model_name="test-fast",
    )

    decision = guardrails.apply(
        candidate=candidate,
        baseline_messages=baseline,
        allowed_context=(
            "Анна ждёт финальный файл по бюджету.",
            "Когда сможешь скинуть финальный файл по бюджету?",
        ),
        profile=profile,
        persona_state=persona_state,
    )

    assert decision.used_fallback is True
    assert decision.messages == baseline
    assert "сильное_отклонение_от_baseline" in decision.flags


def _build_profile() -> StyleProfileSnapshot:
    return StyleProfileSnapshot(
        id=1,
        key="friend_explain",
        title="Друг, объяснить по-человечески",
        description="Тестовый профиль",
        sort_order=10,
        message_mode="series",
        target_message_count=2,
        max_message_count=3,
        avg_length_hint="short",
        punctuation_level="low",
        profanity_level="none",
        warmth_level="medium",
        directness_level="medium",
        explanation_pattern=("коротко",),
        preferred_openers=("ну", "а"),
        preferred_closers=("если что добью дальше",),
        avoid_patterns=("благодарю",),
        casing_mode="mostly_lower",
        rhythm_mode="telegram_bursts",
    )


def _build_persona_state() -> PersonaState:
    return PersonaState(
        enabled=True,
        version="owner-core-v1",
        core=OwnerPersonaCore.from_payload(
            {
                "core_speech_rules": ["коротко"],
                "explanation_pattern": ["сузить смысл"],
                "warmth_rules": ["без сахара"],
                "directness_rules": ["прямо"],
                "profanity_rules": ["без перегиба"],
                "anti_pattern_rules": ["нельзя звучать слишком умно и академично"],
                "opener_bank": ["ну", "а"],
                "closer_bank": ["если что добью дальше"],
                "rewrite_constraints": ["mostly_lower"],
            }
        ),
        guardrails=PersonaGuardrailConfig.from_payload(
            {
                "checks": ["message_count", "average_length", "literary_tone", "bot_phrases"],
                "max_messages": 4,
                "max_message_length": 86,
                "max_average_message_length": 58,
                "max_exclamation_count": 1,
                "max_periods_per_message": 1,
                "max_repeated_openers": 1,
                "max_strong_profane_tokens": 0,
                "literary_patterns": ["в данном случае", "благодарю"],
                "bot_patterns": ["буду рад помочь"],
                "forbidden_patterns": ["!!!"],
            }
        ),
        source="tests",
    )
