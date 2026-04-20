from aiogram import Dispatcher

from bot.handlers.start import router as start_router


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(start_router)
    return dispatcher
