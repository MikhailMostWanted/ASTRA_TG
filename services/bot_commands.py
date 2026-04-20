from dataclasses import dataclass

from aiogram.types import BotCommand


@dataclass(frozen=True, slots=True)
class BotCommandSpec:
    command: str
    description: str


BOT_COMMAND_SPECS: tuple[BotCommandSpec, ...] = (
    BotCommandSpec("start", "Короткий старт и онбординг"),
    BotCommandSpec("help", "Список доступных команд"),
    BotCommandSpec("status", "Текущий статус проекта"),
    BotCommandSpec("sources", "Все разрешённые источники"),
    BotCommandSpec("source_add", "Добавить источник в allowlist"),
    BotCommandSpec("source_disable", "Выключить источник"),
    BotCommandSpec("source_enable", "Включить источник обратно"),
    BotCommandSpec("digest_target", "Сохранить чат или канал для digest"),
    BotCommandSpec("settings", "Показать базовые настройки"),
)


def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command=spec.command, description=spec.description)
        for spec in BOT_COMMAND_SPECS
    ]
