from __future__ import annotations

from services.memory_common import looks_like_conflict


LOW_SIGNAL_MARKERS = {
    "+",
    "++",
    "ага",
    "ок",
    "окей",
    "понял",
    "поняла",
    "понятно",
    "принято",
    "спасибо",
    "спс",
    "хорошо",
    "хорошо.",
    "ясно",
}
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
    "можешь",
)
OPEN_LOOP_MARKERS = (
    "жду",
    "потом",
    "позже",
    "к вечеру",
    "вечером",
    "вернусь",
    "обсудим",
    "продолжим",
    "напомни",
    "апдейт",
    "итог",
)
FOLLOW_UP_COMMITMENT_MARKERS = (
    "смотрю",
    "проверю",
    "вернусь",
    "отпишусь",
    "дам апдейт",
    "скину",
    "пришлю",
    "напишу",
    "добью",
    "к вечеру",
    "вечером",
    "чуть позже",
)
RESOLUTION_MARKERS = (
    "уже отправил",
    "уже скинул",
    "отправил",
    "скинул",
    "прислал",
    "готово",
    "сделал",
    "добавил",
    "залил",
    "загрузил",
    "в почту",
    "на почту",
    "во вложении",
)
EMOTIONAL_MARKERS = (
    "важно",
    "срочно",
    "пережива",
    "волную",
    "обидно",
    "бесит",
    "неприятно",
    "жесть",
)

_STRIP_CHARS = ".,!?():;\"'«»[]{}+-"


def normalize_reply_text(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def reply_tokens(text: str | None) -> tuple[str, ...]:
    normalized = normalize_reply_text(text).casefold()
    return tuple(
        token
        for token in (part.strip(_STRIP_CHARS) for part in normalized.split())
        if token
    )


def is_low_signal_text(text: str | None) -> bool:
    normalized = normalize_reply_text(text)
    if not normalized:
        return False

    lowered = normalized.casefold()
    if lowered in LOW_SIGNAL_MARKERS:
        return True

    tokens = reply_tokens(normalized)
    if not tokens:
        return lowered in LOW_SIGNAL_MARKERS
    return len(tokens) <= 3 and all(token in LOW_SIGNAL_MARKERS for token in tokens)


def has_question_signal(text: str | None) -> bool:
    normalized = normalize_reply_text(text)
    if not normalized:
        return False
    return "?" in normalized or any(token in QUESTION_WORDS for token in reply_tokens(normalized))


def has_request_signal(text: str | None) -> bool:
    lowered = normalize_reply_text(text).casefold()
    if not lowered:
        return False
    return any(marker in lowered for marker in REQUEST_MARKERS)


def has_open_loop_signal(text: str | None) -> bool:
    lowered = normalize_reply_text(text).casefold()
    if not lowered:
        return False
    return any(marker in lowered for marker in OPEN_LOOP_MARKERS)


def has_follow_up_commitment_signal(text: str | None) -> bool:
    lowered = normalize_reply_text(text).casefold()
    if not lowered:
        return False
    return any(marker in lowered for marker in FOLLOW_UP_COMMITMENT_MARKERS)


def has_resolution_signal(text: str | None) -> bool:
    lowered = normalize_reply_text(text).casefold()
    if not lowered:
        return False
    return any(marker in lowered for marker in RESOLUTION_MARKERS)


def has_emotional_signal(text: str | None) -> bool:
    normalized = normalize_reply_text(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    return looks_like_conflict(normalized) or any(marker in lowered for marker in EMOTIONAL_MARKERS)


def pick_focus_label(text: str | None) -> str:
    if has_question_signal(text):
        return "вопрос"
    if has_request_signal(text):
        return "просьба"
    if has_open_loop_signal(text):
        return "незакрытая тема"
    if has_emotional_signal(text):
        return "эмоциональный сигнал"
    if is_low_signal_text(text):
        return "низкий сигнал"
    return "продолжение темы"
