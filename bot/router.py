from aiogram import Dispatcher

from bot.handlers.ingest import router as ingest_router
from bot.handlers.management import router as management_router
from bot.handlers.reminders import router as reminders_router
from bot.handlers.setup import router as setup_router
from bot.handlers.start import router as start_router


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(start_router)
    dispatcher.include_router(setup_router)
    dispatcher.include_router(management_router)
    dispatcher.include_router(reminders_router)
    dispatcher.include_router(ingest_router)
    return dispatcher
