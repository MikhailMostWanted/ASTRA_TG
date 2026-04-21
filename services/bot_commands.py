from dataclasses import dataclass

from aiogram.types import BotCommand


@dataclass(frozen=True, slots=True)
class BotCommandSection:
    key: str
    title: str


@dataclass(frozen=True, slots=True)
class BotCommandSpec:
    command: str
    description: str
    section: str


BOT_COMMAND_SECTIONS: tuple[BotCommandSection, ...] = (
    BotCommandSection("setup", "Настройка"),
    BotCommandSection("sources", "Источники"),
    BotCommandSection("digest", "Digest"),
    BotCommandSection("memory", "Память"),
    BotCommandSection("reply", "Ответы"),
    BotCommandSection("reminders", "Напоминания"),
    BotCommandSection("provider", "Provider"),
    BotCommandSection("fullaccess", "Full-access experimental"),
    BotCommandSection("diagnostics", "Диагностика"),
)


BOT_COMMAND_SPECS: tuple[BotCommandSpec, ...] = (
    BotCommandSpec("start", "Короткий вход и привязка owner chat", "setup"),
    BotCommandSpec("onboarding", "Быстрый first-run guide", "setup"),
    BotCommandSpec("help", "Список команд по разделам", "setup"),
    BotCommandSpec("status", "Короткая живая сводка состояния", "diagnostics"),
    BotCommandSpec("checklist", "Пошаговая operational checklist", "diagnostics"),
    BotCommandSpec("doctor", "Диагностика и предупреждения", "diagnostics"),
    BotCommandSpec("sources", "Все разрешённые источники", "sources"),
    BotCommandSpec("source_add", "Добавить источник в allowlist", "sources"),
    BotCommandSpec("source_disable", "Выключить источник", "sources"),
    BotCommandSpec("source_enable", "Включить источник обратно", "sources"),
    BotCommandSpec("digest_target", "Сохранить чат или канал для digest", "digest"),
    BotCommandSpec("digest_now", "Собрать digest по сохранённым сообщениям", "digest"),
    BotCommandSpec("digest_llm", "Собрать digest с optional LLM-refine", "digest"),
    BotCommandSpec("memory_rebuild", "Пересобрать память по локальной БД", "memory"),
    BotCommandSpec("chat_memory", "Показать memory-карту чата", "memory"),
    BotCommandSpec("person_memory", "Показать memory-карту человека", "memory"),
    BotCommandSpec("reply", "Подсказать ответ по локальному контексту", "reply"),
    BotCommandSpec("reply_llm", "Подсказать ответ с optional LLM-refine", "reply"),
    BotCommandSpec("examples_rebuild", "Пересобрать локальные reply examples", "reply"),
    BotCommandSpec("reply_examples", "Показать похожие прошлые ответы", "reply"),
    BotCommandSpec("style_profiles", "Показать доступные style-профили", "reply"),
    BotCommandSpec("style_set", "Назначить style-профиль для чата", "reply"),
    BotCommandSpec("style_unset", "Снять ручной style-override", "reply"),
    BotCommandSpec("style_status", "Показать эффективный style-профиль для чата", "reply"),
    BotCommandSpec("persona_status", "Показать состояние owner persona layer", "reply"),
    BotCommandSpec("reminders_scan", "Найти кандидаты в задачи и reminders", "reminders"),
    BotCommandSpec("tasks", "Показать активные задачи", "reminders"),
    BotCommandSpec("reminders", "Показать активные reminders", "reminders"),
    BotCommandSpec("provider_status", "Статус optional provider layer", "provider"),
    BotCommandSpec("fullaccess_status", "Статус experimental full-access слоя", "fullaccess"),
    BotCommandSpec("fullaccess_login", "Запросить или завершить user-auth full-access", "fullaccess"),
    BotCommandSpec("fullaccess_logout", "Локально сбросить user-session full-access", "fullaccess"),
    BotCommandSpec("fullaccess_chats", "Показать доступные user-чаты full-access", "fullaccess"),
    BotCommandSpec("fullaccess_sync", "Ручной sync истории одного user-чата", "fullaccess"),
    BotCommandSpec("settings", "Показать базовые настройки", "diagnostics"),
)


def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command=spec.command, description=spec.description)
        for spec in BOT_COMMAND_SPECS
    ]


def iter_command_sections() -> tuple[BotCommandSection, ...]:
    return BOT_COMMAND_SECTIONS
