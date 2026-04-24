from __future__ import annotations

import re
from collections.abc import Iterable


ASSISTANT_TONE_PATTERNS = (
    "я бы ответил",
    "можно написать",
    "предлагаю ответить",
    "с учётом контекста",
    "с учетом контекста",
    "данный ответ",
    "оптимальным вариантом будет",
    "вариант ответа",
    "готовый вариант",
)
OWNER_STYLE_OPENERS = (
    "ну",
    "да",
    "не",
    "не не",
    "а",
    "слушай",
    "смотри",
    "короче",
    "типо",
    "ща",
    "щас",
    "окей",
    "давай",
)
ROUGH_PROFANITY = (
    "блять",
    "бля",
    "пиздец",
    "хуйня",
    "хуй",
    "пизд",
    "ебан",
    "нахуй",
)
SOFT_PROFANITY_REPLACEMENTS = {
    "блять": "",
    "бля": "",
    "пиздец": "жесть",
    "хуйня": "фигня",
    "нахуй": "",
    "хуй": "",
}


def postprocess_variant_text(
    value: str | Iterable[str] | None,
    *,
    variant_id: str,
    opener_hint: str | None = None,
    max_lines: int | None = None,
) -> str:
    messages = postprocess_variant_messages(
        _coerce_messages(value),
        variant_id=variant_id,
        opener_hint=opener_hint,
        max_lines=max_lines,
    )
    return "\n".join(messages).strip()


def postprocess_variant_messages(
    messages: Iterable[str],
    *,
    variant_id: str,
    opener_hint: str | None = None,
    max_lines: int | None = None,
) -> tuple[str, ...]:
    normalized_id = normalize_variant_id(variant_id)
    cleaned = [_clean_line(message) for message in messages]
    cleaned = [message for message in cleaned if message]
    if not cleaned:
        return ()

    if normalized_id == "owner_style":
        cleaned = _cascade_owner_style(cleaned, opener_hint=opener_hint)
    elif normalized_id == "short":
        cleaned = _shorten(cleaned)
    elif normalized_id == "soft":
        cleaned = _soften(cleaned)
    else:
        cleaned = _telegram_lines(cleaned, max_line_words=12, max_lines=4)

    if normalized_id == "soft":
        cleaned = [_remove_rough_profanity(message) for message in cleaned]
    elif normalized_id == "owner_style":
        cleaned = _cap_owner_profanity(cleaned, max_count=1)

    cleaned = [_strip_short_final_period(message) for message in cleaned if message]
    cleaned = [message for message in cleaned if message]
    if max_lines is not None:
        cleaned = _trim_lines(cleaned, max_lines=max_lines)
    return tuple(cleaned)


def normalize_variant_id(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"style", "my_style", "owner", "ownerstyle", "owner-style"}:
        return "owner_style"
    if normalized in {"primary", "short", "soft", "owner_style"}:
        return normalized
    return normalized or "primary"


def contains_assistant_tone(value: str | Iterable[str]) -> bool:
    text = "\n".join(_coerce_messages(value)).casefold()
    return any(pattern in text for pattern in ASSISTANT_TONE_PATTERNS)


def count_rough_profanity(value: str | Iterable[str]) -> int:
    text = "\n".join(_coerce_messages(value)).casefold()
    return sum(text.count(token) for token in ROUGH_PROFANITY)


def _coerce_messages(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(line for line in value.splitlines() if line.strip()) or ((value,) if value.strip() else ())
    return tuple(str(item) for item in value if str(item).strip())


def _clean_line(value: object) -> str:
    cleaned = str(value or "")
    cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "")
    cleaned = re.sub(r"[*_`#>]+", "", cleaned)
    cleaned = re.sub(r"^\s*[-•]\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\d+[\).]\s*", "", cleaned)
    cleaned = _strip_wrapping_quotes(cleaned)
    cleaned = _remove_assistant_prefix(cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    cleaned = cleaned.strip(" \t\r\n\"'«»“”")
    return cleaned


def _strip_wrapping_quotes(value: str) -> str:
    cleaned = value.strip()
    pairs = (("\"", "\""), ("'", "'"), ("«", "»"), ("“", "”"))
    changed = True
    while changed and len(cleaned) >= 2:
        changed = False
        for left, right in pairs:
            if cleaned.startswith(left) and cleaned.endswith(right):
                cleaned = cleaned[1:-1].strip()
                changed = True
                break
    return cleaned


def _remove_assistant_prefix(value: str) -> str:
    cleaned = value.strip()
    prefix_pattern = re.compile(
        r"^\s*(?:"
        r"я\s+бы\s+ответил(?:а)?(?:\s+так)?|"
        r"можно\s+написать|"
        r"предлагаю\s+ответить|"
        r"с\s+уч[её]том\s+контекста|"
        r"данный\s+ответ|"
        r"оптимальным\s+вариантом\s+будет|"
        r"вариант\s+ответа|"
        r"готовый\s+вариант|"
        r"ответ"
        r")\s*[:—-]?\s*",
        re.IGNORECASE,
    )
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = prefix_pattern.sub("", cleaned).strip()
    return cleaned


def _telegram_lines(
    messages: list[str],
    *,
    max_line_words: int,
    max_lines: int,
) -> list[str]:
    lines: list[str] = []
    for message in messages:
        parts = _split_by_natural_breaks(message)
        for part in parts:
            lines.extend(_split_by_word_limit(part, max_line_words=max_line_words))
    return _trim_lines([line for line in lines if line], max_lines=max_lines)


def _cascade_owner_style(messages: list[str], *, opener_hint: str | None) -> list[str]:
    lines = _telegram_lines(messages, max_line_words=8, max_lines=4)
    if not lines:
        return []
    opener = _normalize_opener(opener_hint)
    if opener and not _starts_with_owner_opener(lines[0]):
        if len(lines[0].split()) <= 6:
            lines[0] = f"{opener} {lines[0]}".strip()
        else:
            lines.insert(0, opener)
    if len(lines) == 1 and len(lines[0].split()) > 8:
        lines = _split_by_word_limit(lines[0], max_line_words=6)
    return _trim_lines(lines, max_lines=4)


def _shorten(messages: list[str]) -> list[str]:
    lines: list[str] = []
    for message in messages:
        for part in _split_by_natural_breaks(message):
            lines.extend(_split_by_word_limit(part, max_line_words=7))
    if not lines:
        return []
    if len(lines) > 1:
        return [line for line in lines[:2] if line]
    words = lines[0].split()
    if len(words) > 8:
        return [" ".join(words[:8]).strip()]
    return lines


def _soften(messages: list[str]) -> list[str]:
    joined = "\n".join(messages)
    replacements = (
        (r"\bнадо\b", "лучше"),
        (r"\bнужно\b", "лучше"),
        (r"\bсрочно\b", "как сможешь"),
        (r"\bразберись\b", "давай спокойно разберёмся"),
        (r"\bне тупи\b", "давай спокойно"),
    )
    softened = joined
    for source, target in replacements:
        softened = re.sub(source, target, softened, flags=re.IGNORECASE)
    lines = _telegram_lines(softened.splitlines(), max_line_words=10, max_lines=3)
    if lines and not lines[0].casefold().startswith(("да", "ну", "я", "понял", "поняла", "понимаю")):
        lines.insert(0, "да я понял тебя")
    return _trim_lines(lines, max_lines=3)


def _split_by_natural_breaks(value: str) -> list[str]:
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return []
    if "\n" in value:
        return [line.strip(" ,.!?;:-") for line in value.splitlines() if line.strip()]
    chunks = re.split(
        r"(?<=[.!?])\s+|,\s+|\s+потому что\s+|\s+но\s+|\s+и\s+|\s+чтобы\s+|\s+если\s+",
        cleaned,
    )
    result = [chunk.strip(" ,.!?;:-") for chunk in chunks if chunk.strip(" ,.!?;:-")]
    return result or [cleaned.strip(" ,.!?;:-")]


def _split_by_word_limit(value: str, *, max_line_words: int) -> list[str]:
    words = value.split()
    if len(words) <= max_line_words:
        return [value.strip(" ,.!?;:-")]
    chunks: list[str] = []
    for index in range(0, len(words), max_line_words):
        chunk = " ".join(words[index : index + max_line_words]).strip(" ,.!?;:-")
        if chunk:
            chunks.append(chunk)
    return chunks


def _trim_lines(lines: list[str], *, max_lines: int) -> list[str]:
    normalized = [line.strip() for line in lines if line.strip()]
    if len(normalized) <= max_lines:
        return normalized
    head = normalized[: max_lines - 1]
    tail = " ".join(normalized[max_lines - 1 :]).strip()
    if tail:
        head.append(tail)
    return head[:max_lines]


def _strip_short_final_period(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned.split()) <= 8:
        cleaned = cleaned.rstrip(".")
    return cleaned.strip()


def _remove_rough_profanity(value: str) -> str:
    cleaned = value
    for source, target in SOFT_PROFANITY_REPLACEMENTS.items():
        cleaned = re.sub(rf"\b{re.escape(source)}\b", target, cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" ,.!?;:-")


def _cap_owner_profanity(messages: list[str], *, max_count: int) -> list[str]:
    seen = 0
    capped: list[str] = []
    for message in messages:
        updated = message
        for token in ROUGH_PROFANITY:
            matches = list(re.finditer(rf"\b{re.escape(token)}\b", updated, flags=re.IGNORECASE))
            for match in reversed(matches):
                seen += 1
                if seen <= max_count:
                    continue
                replacement = SOFT_PROFANITY_REPLACEMENTS.get(token, "")
                updated = f"{updated[: match.start()]}{replacement}{updated[match.end():]}"
        capped.append(" ".join(updated.split()).strip(" ,.!?;:-"))
    return capped


def _normalize_opener(value: str | None) -> str | None:
    if not value:
        return None
    normalized = " ".join(value.casefold().split()).strip(" ,.!?;:-")
    return normalized if normalized in OWNER_STYLE_OPENERS else None


def _starts_with_owner_opener(value: str) -> bool:
    lowered = value.casefold()
    return any(lowered == opener or lowered.startswith(f"{opener} ") for opener in OWNER_STYLE_OPENERS)
