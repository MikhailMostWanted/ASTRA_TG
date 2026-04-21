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
    ReplyRefinementCandidate,
    RewriteReplyRequest,
)


@dataclass(slots=True)
class OpenAICompatibleProvider(BaseProvider):
    base_url: str
    api_key: str
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
        messages = _extract_reply_messages(raw_text)
        if not messages:
            raise ProviderResponseError("Provider вернул пустой reply refine ответ.")
        return ReplyRefinementCandidate(
            messages=messages,
            raw_text=raw_text,
            model_name=self.model_fast,
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
            "temperature": 0.2,
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
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
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


def _extract_reply_messages(raw_text: str) -> tuple[str, ...]:
    messages: list[str] = []
    for line in raw_text.splitlines():
        cleaned = _normalize_text(line.lstrip("-•1234567890. ").strip())
        if cleaned:
            messages.append(cleaned)
    if messages:
        return tuple(messages[:4])
    normalized = _normalize_text(raw_text)
    return (normalized,) if normalized else ()


def _extract_json_payload(raw_text: str) -> dict[str, object]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```JSON")
        cleaned = cleaned.removeprefix("```").removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ProviderResponseError("Provider не вернул валидный JSON для digest improve.") from error
    if not isinstance(payload, dict):
        raise ProviderResponseError("Digest improve JSON должен быть объектом.")
    return payload


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
