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
    BotCommandSpec("memory_rebuild", "Пересобрать память по локальной БД"),
    BotCommandSpec("chat_memory", "Показать memory-карту чата"),
    BotCommandSpec("person_memory", "Показать memory-карту человека"),
    BotCommandSpec("digest_target", "Сохранить чат или канал для digest"),
    BotCommandSpec("digest_now", "Собрать digest по сохранённым сообщениям"),
    BotCommandSpec("settings", "Показать базовые настройки"),
)


def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command=spec.command, description=spec.description)
        for spec in BOT_COMMAND_SPECS
    ]
