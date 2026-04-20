from aiogram import Dispatcher

from bot.handlers.ingest import router as ingest_router
from bot.handlers.management import router as management_router
from bot.handlers.start import router as start_router


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(start_router)
    dispatcher.include_router(management_router)
    dispatcher.include_router(ingest_router)
    return dispatcher
