from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

from aiogram.types import CallbackQuery, Message

from core.logging import get_logger, log_event
from services.providers.errors import ProviderError


def user_safe_handler(
    event_name: str,
    *,
    fallback_message: str = "Операция не выполнена.",
    silent: bool = False,
):
    def decorator(handler: Callable[..., Awaitable[Any]]):
        logger = get_logger(handler.__module__)

        @wraps(handler)
        async def wrapped(*args, **kwargs):
            event = args[0] if args else None
            try:
                return await handler(*args, **kwargs)
            except Exception as error:
                user_message = _map_user_message(error, fallback_message=fallback_message)
                log_event(
                    logger,
                    40,
                    f"{event_name}.failed",
                    "Обработчик завершился ошибкой.",
                    error_type=type(error).__name__,
                    user_message=user_message,
                    chat_id=_extract_chat_id(event),
                    handler=handler.__name__,
                )
                if not silent:
                    await _respond(event, user_message)
                return None

        return wrapped

    return decorator


async def _respond(event: Any, message: str) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(message, show_alert=True)
        return
    if isinstance(event, Message) or hasattr(event, "answer"):
        await event.answer(message)


def _map_user_message(error: Exception, *, fallback_message: str) -> str:
    message = str(error).strip()
    lowered = message.lower()

    if isinstance(error, ProviderError):
        return "Провайдер сейчас недоступен."
    if "источник" in lowered and "не найден" in lowered:
        return "Источник не найден."
    if "provider" in lowered or "llm" in lowered:
        return "Провайдер сейчас недоступен."
    if "full-access" in lowered or "fullaccess" in lowered:
        return "full-access не настроен."
    if isinstance(error, ValueError) and message:
        return message
    return fallback_message


def _extract_chat_id(event: Any) -> int | None:
    chat = getattr(event, "chat", None)
    chat_id = getattr(chat, "id", None)
    if isinstance(chat_id, int):
        return chat_id
    message = getattr(event, "message", None)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if isinstance(chat_id, int):
        return chat_id
    return None
