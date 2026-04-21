from __future__ import annotations

from typing import cast

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.common import remember_owner_chat_if_private
from services.digest_engine import MessageSenderProtocol
from services.error_handling import user_safe_handler
from services.inline_navigation import parse_inline_route
from services.setup_ui import SetupUIService


router = Router(name=__name__)


@router.message(Command("setup"))
@user_safe_handler("bot.setup")
async def handle_setup_command(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await remember_owner_chat_if_private(message, session)
        card = await SetupUIService.from_session(session).build_screen("home")

    await message.answer(card.text, reply_markup=card.reply_markup)


@router.callback_query(F.data.startswith("ux:"))
@user_safe_handler("bot.setup_callback")
async def handle_setup_callback(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    parsed = parse_inline_route(callback.data)
    if parsed is None or parsed.screen is None:
        await callback.answer("Некорректный setup callback.", show_alert=True)
        return

    callback_message = getattr(callback, "message", None)
    async with session_factory() as session:
        if callback_message is not None and hasattr(callback_message, "chat"):
            await remember_owner_chat_if_private(callback_message, session)

        service = SetupUIService.from_session(session)
        if parsed.kind in {"screen", "refresh", "back"}:
            card = await service.build_screen(parsed.screen)
            await _edit_card(callback_message, card)
            await callback.answer()
            return

        if parsed.kind == "digest_run":
            sender = _resolve_sender(callback=callback, callback_message=callback_message)
            preview_chat_id = _extract_chat_id(callback_message)
            notice = await service.run_digest(
                window_argument=parsed.arg or "24h",
                preview_chat_id=preview_chat_id,
                sender=sender,
            )
            await session.commit()
            if notice and hasattr(callback_message, "answer"):
                await callback_message.answer(notice)
            card = await service.build_screen(parsed.screen)
            await _edit_card(callback_message, card)
            await callback.answer("Дайджест собран.")
            return

        if parsed.kind == "memory_rebuild":
            result = await service.rebuild_memory()
            await session.commit()
            if hasattr(callback_message, "answer"):
                await callback_message.answer(result.to_user_message())
            card = await service.build_screen(parsed.screen)
            await _edit_card(callback_message, card)
            await callback.answer("Память пересобрана.")
            return

        if parsed.kind == "reminders_scan":
            result = await service.run_reminders_scan(window_argument=parsed.arg or "24h")
            await session.commit()
            if hasattr(callback_message, "answer"):
                await callback_message.answer(result.summary_text)
                for item in result.cards:
                    await callback_message.answer(item.text, reply_markup=item.reply_markup)
            card = await service.build_screen(parsed.screen)
            await _edit_card(callback_message, card)
            await callback.answer("Скан завершён.")
            return

        if parsed.kind == "reminders_tasks":
            if hasattr(callback_message, "answer"):
                await callback_message.answer(await service.build_tasks_message())
            await callback.answer("Список задач отправлен.")
            return

        if parsed.kind == "reminders_list":
            if hasattr(callback_message, "answer"):
                await callback_message.answer(await service.build_reminders_message())
            await callback.answer("Список напоминаний отправлен.")
            return

    await callback.answer("Действие пока не поддержано.", show_alert=True)


async def _edit_card(callback_message: object | None, card) -> None:
    if callback_message is None or not hasattr(callback_message, "edit_text"):
        raise RuntimeError("Невозможно обновить setup-экран: callback message недоступно.")
    await callback_message.edit_text(card.text, reply_markup=card.reply_markup)


def _extract_chat_id(callback_message: object | None) -> int:
    chat = getattr(callback_message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if not isinstance(chat_id, int):
        raise RuntimeError("Невозможно определить chat_id для setup callback.")
    return chat_id


def _resolve_sender(
    *,
    callback: CallbackQuery,
    callback_message: object | None,
) -> MessageSenderProtocol:
    sender = getattr(callback, "bot", None) or getattr(callback_message, "bot", None)
    if sender is None:
        raise RuntimeError("Aiogram bot недоступен в setup callback.")
    return cast(MessageSenderProtocol, sender)
