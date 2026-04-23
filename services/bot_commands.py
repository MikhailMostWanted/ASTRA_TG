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
    BotCommandSection("digest", "Дайджест"),
    BotCommandSection("memory", "Память"),
    BotCommandSection("reply", "Ответы"),
    BotCommandSection("reminders", "Напоминания"),
    BotCommandSection("provider", "Провайдер"),
    BotCommandSection("fullaccess", "Full-access"),
    BotCommandSection("diagnostics", "Диагностика"),
)


BOT_COMMAND_SPECS: tuple[BotCommandSpec, ...] = (
    BotCommandSpec("start", "Короткий вход и привязка чата владельца", "setup"),
    BotCommandSpec("onboarding", "Быстрый стартовый маршрут", "setup"),
    BotCommandSpec("help", "Список команд по разделам", "setup"),
    BotCommandSpec("setup", "Главный экран настройки и навигации", "setup"),
    BotCommandSpec("status", "Короткий статус без тех. перегруза", "diagnostics"),
    BotCommandSpec("checklist", "Пошаговый рабочий чеклист", "diagnostics"),
    BotCommandSpec("doctor", "Глубокая диагностика и предупреждения", "diagnostics"),
    BotCommandSpec("sources", "Все разрешённые источники", "sources"),
    BotCommandSpec("source_add", "Добавить источник в список разрешённых", "sources"),
    BotCommandSpec("source_disable", "Выключить источник", "sources"),
    BotCommandSpec("source_enable", "Включить источник обратно", "sources"),
    BotCommandSpec("digest_target", "Сохранить чат или канал для дайджеста", "digest"),
    BotCommandSpec("digest_now", "Собрать дайджест по сохранённым сообщениям", "digest"),
    BotCommandSpec("digest_llm", "Собрать дайджест с LLM-улучшением", "digest"),
    BotCommandSpec("memory_rebuild", "Пересобрать память по локальной БД", "memory"),
    BotCommandSpec("chat_memory", "Показать карту памяти чата", "memory"),
    BotCommandSpec("person_memory", "Показать карту памяти человека", "memory"),
    BotCommandSpec("reply", "Подсказать ответ по локальному контексту", "reply"),
    BotCommandSpec("reply_llm", "Подсказать ответ с LLM-улучшением", "reply"),
    BotCommandSpec("examples_rebuild", "Пересобрать локальные примеры ответов", "reply"),
    BotCommandSpec("reply_examples", "Показать похожие прошлые ответы", "reply"),
    BotCommandSpec("style_profiles", "Показать доступные профили стиля", "reply"),
    BotCommandSpec("style_set", "Назначить профиль стиля для чата", "reply"),
    BotCommandSpec("style_unset", "Снять ручной стиль чата", "reply"),
    BotCommandSpec("style_status", "Показать эффективный профиль стиля для чата", "reply"),
    BotCommandSpec("persona_status", "Показать состояние слоя персоны владельца", "reply"),
    BotCommandSpec("reminders_scan", "Найти кандидаты в задачи и напоминания", "reminders"),
    BotCommandSpec("tasks", "Показать активные задачи", "reminders"),
    BotCommandSpec("reminders", "Показать активные reminders", "reminders"),
    BotCommandSpec("provider_status", "Статус дополнительного слоя провайдера", "provider"),
    BotCommandSpec("fullaccess_status", "Статус full-access слоя", "fullaccess"),
    BotCommandSpec("fullaccess_login", "Безопасно запросить код для локального full-access входа", "fullaccess"),
    BotCommandSpec("fullaccess_logout", "Локально сбросить пользовательскую full-access сессию", "fullaccess"),
    BotCommandSpec("fullaccess_chats", "Показать доступные пользовательские чаты full-access", "fullaccess"),
    BotCommandSpec("fullaccess_sync", "Ручная синхронизация истории одного пользовательского чата", "fullaccess"),
    BotCommandSpec("settings", "Показать базовые настройки", "diagnostics"),
)


def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command=spec.command, description=spec.description)
        for spec in BOT_COMMAND_SPECS
    ]


def iter_command_sections() -> tuple[BotCommandSection, ...]:
    return BOT_COMMAND_SECTIONS
