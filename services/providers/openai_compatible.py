from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request

from services.providers.base import BaseProvider
from services.providers.errors import ProviderResponseError, ProviderUnavailableError
from services.providers.models import (
    DigestImproveRequest,
    DigestImprovementCandidate,
    ProviderPrompt,
    ProviderTask,
    ReplyRefinementCandidate,
    ReplyVariantCandidate,
    RewriteReplyRequest,
)
from services.reply_postprocessor import normalize_variant_id, postprocess_variant_messages


@dataclass(slots=True)
class OpenAICompatibleProvider(BaseProvider):
    base_url: str
    api_key: str | None
    model_fast: str
    model_deep: str
    timeout_seconds: float = 15.0
    name: str = "openai_compatible"

    async def check_health(self) -> tuple[bool, str]:
        try:
            await asyncio.to_thread(self._request_json, "GET", "/models")
        except ProviderUnavailableError as error:
            return False, str(error)
        except ProviderResponseError as error:
            return False, str(error)
        return True, "API доступен."

    async def rewrite_reply(
        self,
        request: RewriteReplyRequest,
    ) -> ReplyRefinementCandidate:
        raw_text = await self._complete(
            prompt=request.prompt,
            model_name=self.model_fast,
        )
        parsed = _extract_reply_payload(raw_text)
        variants = parsed.variants
        if variants:
            primary_text = next(
                (variant.text for variant in variants if variant.id == "primary"),
                None,
            )
            messages = _extract_reply_messages(primary_text or "")
        else:
            messages = _extract_reply_messages(raw_text)
        if not messages:
            raise ProviderResponseError("Provider вернул пустой reply refine ответ.")
        return ReplyRefinementCandidate(
            messages=messages,
            raw_text=raw_text,
            model_name=self.model_fast,
            variants=variants,
            should_reply=parsed.should_reply,
            reason=parsed.reason,
            confidence=parsed.confidence,
            parse_recovered=parsed.recovered,
        )

    async def improve_digest(
        self,
        request: DigestImproveRequest,
    ) -> DigestImprovementCandidate:
        raw_text = await self._complete(
            prompt=request.prompt,
            model_name=self.model_deep,
        )
        payload = _extract_json_payload(raw_text)
        summary_short = _normalize_text(payload.get("summary_short"))
        overview_lines = _normalize_lines(payload.get("overview_lines"))
        key_source_lines = _normalize_lines(payload.get("key_source_lines"))
        if not summary_short or not overview_lines or not key_source_lines:
            raise ProviderResponseError(
                "Provider вернул неполный digest refine ответ."
            )
        return DigestImprovementCandidate(
            summary_short=summary_short,
            overview_lines=overview_lines,
            key_source_lines=key_source_lines,
            raw_text=raw_text,
            model_name=self.model_deep,
        )

    async def _complete(
        self,
        *,
        prompt: ProviderPrompt,
        model_name: str,
    ) -> str:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": prompt.system_instructions},
                {"role": "user", "content": prompt.user_input},
            ],
            "temperature": 0.35 if prompt.task == ProviderTask.REWRITE_REPLY else 0.0,
            "stream": False,
            "think": False,
            "reasoning_effort": "none",
            "max_tokens": _max_tokens_for_task(prompt.task),
        }
        response_payload = await asyncio.to_thread(
            self._request_json,
            "POST",
            "/chat/completions",
            payload,
        )
        return _extract_completion_text(response_payload)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        headers = {
            "Accept": "application/json",
        }
        api_key = _normalize_text(self.api_key)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")

        request = urllib_request.Request(
            url=self._build_url(path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as error:
            raw_body = error.read().decode("utf-8", errors="ignore")
            raise ProviderUnavailableError(
                f"HTTP {error.code} от provider API: {raw_body or error.reason}"
            ) from error
        except urllib_error.URLError as error:
            raise ProviderUnavailableError(
                f"Не удалось достучаться до provider API: {error.reason}"
            ) from error
        except TimeoutError as error:
            raise ProviderUnavailableError("Provider API не ответил за отведённый таймаут.") from error

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise ProviderResponseError(
                "Provider API вернул не-JSON ответ."
            ) from error

    def _build_url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"


def _extract_completion_text(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderResponseError("Provider вернул ответ без choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ProviderResponseError("Provider вернул невалидный choice.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ProviderResponseError("Provider не вернул message в choice.")
    content = message.get("content")
    if isinstance(content, str):
        text = _normalize_text(content)
        if text:
            return text
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text = _normalize_text(item["text"])
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    raise ProviderResponseError("Provider вернул пустой completion content.")


def _max_tokens_for_task(task: ProviderTask) -> int:
    if task == ProviderTask.REWRITE_REPLY:
        return 280
    if task == ProviderTask.IMPROVE_DIGEST:
        return 384
    return 256


@dataclass(frozen=True, slots=True)
class _ReplyPayload:
    variants: tuple[ReplyVariantCandidate, ...]
    should_reply: bool
    reason: str | None
    confidence: float | None
    recovered: bool


def _extract_reply_messages(raw_text: str) -> tuple[str, ...]:
    messages = postprocess_variant_messages(
        raw_text.splitlines() or (raw_text,),
        variant_id="primary",
    )
    if messages:
        return messages[:4]
    normalized = _normalize_text(raw_text)
    return (normalized,) if normalized else ()


def _extract_reply_payload(raw_text: str) -> _ReplyPayload:
    try:
        payload = _extract_json_payload(raw_text)
    except ProviderResponseError:
        recovered_messages = postprocess_variant_messages(
            raw_text.splitlines() or (raw_text,),
            variant_id="primary",
        )
        variants = (
            (
                ReplyVariantCandidate(
                    id="primary",
                    text="\n".join(recovered_messages),
                ),
            )
            if recovered_messages
            else ()
        )
        return _ReplyPayload(
            variants=variants,
            should_reply=True,
            reason="provider вернул не-JSON, текст восстановлен постобработкой.",
            confidence=None,
            recovered=bool(variants),
        )

    variants: list[ReplyVariantCandidate] = []
    for variant_id in ("primary", "short", "soft", "owner_style", "style"):
        text = _extract_variant_text(payload.get(variant_id))
        if not text:
            continue
        normalized_id = normalize_variant_id(variant_id)
        if any(item.id == normalized_id for item in variants):
            continue
        cleaned = "\n".join(
            postprocess_variant_messages(
                text.splitlines() or (text,),
                variant_id=normalized_id,
            )
        )
        if cleaned:
            variants.append(ReplyVariantCandidate(id=normalized_id, text=cleaned))
    return _ReplyPayload(
        variants=tuple(variants),
        should_reply=_extract_should_reply(payload),
        reason=_normalize_optional_text(payload.get("reason")),
        confidence=_extract_confidence(payload.get("confidence")),
        recovered=False,
    )


def _extract_json_payload(raw_text: str) -> dict[str, object]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```JSON")
        cleaned = cleaned.removeprefix("```").removesuffix("```").strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ProviderResponseError("Provider не вернул валидный JSON.") from error
    if not isinstance(payload, dict):
        raise ProviderResponseError("Provider JSON должен быть объектом.")
    return payload


def _extract_variant_text(value: object) -> str | None:
    if isinstance(value, list):
        parts = [
            _normalize_text(str(item)).lstrip("-•1234567890. ").strip()
            for item in value
            if _normalize_text(str(item))
        ]
        if parts:
            return "\n".join(parts)
    if isinstance(value, str):
        cleaned = _normalize_text(value)
        return cleaned or None
    return None


def _extract_should_reply(payload: dict[str, object]) -> bool:
    value = payload.get("should_reply")
    if isinstance(value, bool):
        return value
    value = payload.get("shouldReply")
    if isinstance(value, bool):
        return value
    mode = _normalize_optional_text(payload.get("mode"))
    if mode and mode.casefold() in {"hold", "no_reply", "no reply"}:
        return False
    return True


def _extract_confidence(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        try:
            return max(0.0, min(1.0, float(value.strip().replace(",", "."))))
        except ValueError:
            return None
    return None


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _normalize_text(value)
    return cleaned or None


def _normalize_lines(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    normalized: list[str] = []
    for item in value:
        line = _normalize_text(str(item))
        if not line:
            continue
        if not line.startswith("- "):
            line = f"- {line.lstrip('- ').strip()}"
        normalized.append(line)
    return tuple(normalized)


def _normalize_text(value: object) -> str:
    return " ".join(str(value).split()).strip()
