from aiogram import Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.common import remember_owner_chat_if_private
from services.message_ingest import MessageIngestService
from storage.repositories import ChatRepository, MessageRepository


router = Router(name=__name__)


@router.message()
async def handle_incoming_message(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _ingest_message(message=message, session_factory=session_factory)


@router.channel_post()
async def handle_incoming_channel_post(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _ingest_message(message=message, session_factory=session_factory)


async def _ingest_message(
    *,
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        owner_saved = await remember_owner_chat_if_private(message, session)
        if owner_saved:
            await session.commit()

        result = await MessageIngestService(
            chat_repository=ChatRepository(session),
            message_repository=MessageRepository(session),
        ).ingest_message(message)
        if result.action == "ignored":
            return

        await session.commit()
