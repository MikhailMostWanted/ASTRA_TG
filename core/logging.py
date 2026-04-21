from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_FIELD_MARKERS = (
    "token",
    "secret",
    "api_key",
    "password",
    "session",
    "hash",
    "phone",
)


class AstraLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        event_name = getattr(record, "event_name", None) or "log"
        context = getattr(record, "context", {}) or {}
        context_text = _format_context(context)
        message = record.getMessage()
        payload = (
            f"{timestamp} level={record.levelname.lower()} logger={record.name} "
            f"event={event_name} msg={json.dumps(message, ensure_ascii=False)}"
        )
        if context_text:
            payload = f"{payload} {context_text}"

        if record.exc_info:
            return f"{payload}\n{self.formatException(record.exc_info)}"
        return payload


def configure_logging(log_level: str) -> None:
    level_name = log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(AstraLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event_name: str,
    message: str,
    **context: Any,
) -> None:
    logger.log(
        level,
        message,
        extra={
            "event_name": event_name,
            "context": _sanitize_context(context),
        },
    )


def log_exception(
    logger: logging.Logger,
    event_name: str,
    error: Exception,
    *,
    message: str | None = None,
    **context: Any,
) -> None:
    log_event(
        logger,
        logging.ERROR,
        event_name,
        message or str(error) or "Необработанная ошибка.",
        exception_type=type(error).__name__,
        **context,
    )
    logger.debug("traceback", exc_info=error)


def _format_context(context: dict[str, Any]) -> str:
    rendered: list[str] = []
    for key, value in context.items():
        rendered.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    return " ".join(rendered)


def _sanitize_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _sanitize_value(key, value)
        for key, value in context.items()
        if value is not None
    }


def _sanitize_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if any(marker in lowered_key for marker in SENSITIVE_FIELD_MARKERS):
        return "[hidden]"

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if len(cleaned) > 160:
            return f"{cleaned[:157]}..."
        return cleaned
    if isinstance(value, dict):
        return {
            nested_key: _sanitize_value(f"{key}.{nested_key}", nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_value(f"{key}[{index}]", nested_value)
            for index, nested_value in enumerate(value)
        ]
    return str(value)
