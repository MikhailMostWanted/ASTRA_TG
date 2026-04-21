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
    BotCommandSpec("provider_status", "Статус optional provider layer"),
    BotCommandSpec("reminders_scan", "Найти кандидаты в задачи и reminders"),
    BotCommandSpec("tasks", "Показать активные задачи"),
    BotCommandSpec("reminders", "Показать активные reminders"),
    BotCommandSpec("sources", "Все разрешённые источники"),
    BotCommandSpec("source_add", "Добавить источник в allowlist"),
    BotCommandSpec("source_disable", "Выключить источник"),
    BotCommandSpec("source_enable", "Включить источник обратно"),
    BotCommandSpec("memory_rebuild", "Пересобрать память по локальной БД"),
    BotCommandSpec("chat_memory", "Показать memory-карту чата"),
    BotCommandSpec("person_memory", "Показать memory-карту человека"),
    BotCommandSpec("digest_target", "Сохранить чат или канал для digest"),
    BotCommandSpec("digest_now", "Собрать digest по сохранённым сообщениям"),
    BotCommandSpec("digest_llm", "Собрать digest с optional LLM-refine"),
    BotCommandSpec("reply", "Подсказать ответ по локальному контексту"),
    BotCommandSpec("reply_llm", "Подсказать ответ с optional LLM-refine"),
    BotCommandSpec("examples_rebuild", "Пересобрать локальные reply examples"),
    BotCommandSpec("reply_examples", "Показать похожие прошлые ответы"),
    BotCommandSpec("style_profiles", "Показать доступные style-профили"),
    BotCommandSpec("style_set", "Назначить style-профиль для чата"),
    BotCommandSpec("style_unset", "Снять ручной style-override"),
    BotCommandSpec("style_status", "Показать эффективный style-профиль для чата"),
    BotCommandSpec("persona_status", "Показать состояние owner persona layer"),
    BotCommandSpec("settings", "Показать базовые настройки"),
)


def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command=spec.command, description=spec.description)
        for spec in BOT_COMMAND_SPECS
    ]
