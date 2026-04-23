from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnboardingFormatter:
    def build_message(self) -> str:
        return (
            "Astra AFT работает по локальной базе сообщений: отсюда строятся дайджест, память, ответы и напоминания.\n\n"
            "Быстрый путь:\n"
            "1. Открой /setup.\n"
            "2. Добавь источник: /source_add или /sources.\n"
            "3. Накопи сообщения. Если нужен импорт истории, используй Full-access в режиме чтения.\n"
            "4. Задай получателя дайджеста: /digest_target.\n"
            "5. Пересобери память: /memory_rebuild.\n"
            "6. Проверь рабочий контур: /digest_now, /reply <chat_id|@username>, /reminders_scan.\n\n"
            "Если что-то не складывается:\n"
            "/checklist — пошагово, что ещё не готово.\n"
            "/doctor — глубже, с причинами и предупреждениями."
        )

    def build_start_message(self) -> str:
        return (
            "Astra AFT готов к работе.\n\n"
            "Открой /setup: там главный экран и следующий шаг.\n"
            "Если нужен короткий старт, смотри /onboarding.\n"
            "Если нужна диагностика: /status, /checklist, /doctor.\n"
            "Все команды по разделам: /help."
        )
