from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnboardingFormatter:
    def build_message(self) -> str:
        return (
            "Astra AFT — Telegram-first инструмент для ingest, digest, memory, reply и reminders "
            "по локальной БД.\n\n"
            "Что уже есть:\n"
            "• источники и ingest\n"
            "• digest\n"
            "• memory\n"
            "• reply\n"
            "• reminders\n"
            "• optional provider\n"
            "• experimental full-access read-only\n\n"
            "Стартовый порядок:\n"
            "1. Добавь хотя бы один источник: /source_add или посмотри /sources.\n"
            "2. Накопи сообщения или подтяни историю через /fullaccess_sync.\n"
            "3. При желании задай канал доставки: /digest_target.\n"
            "4. Построй память: /memory_rebuild.\n"
            "5. Проверь рабочий контур: /digest_now, /reply <chat_id|@username>, /reminders_scan.\n\n"
            "Что смотреть по ходу:\n"
            "/checklist — что уже готово пошагово.\n"
            "/doctor — где проблемы и что чинить дальше."
        )

    def build_start_message(self) -> str:
        return (
            "Astra AFT готов к работе в bot-first режиме.\n\n"
            "Открой /setup, чтобы увидеть готовность и следующий шаг.\n"
            "Стартовый путь: /onboarding.\n"
            "Быстрый self-check: /status, /checklist, /doctor.\n"
            "Список команд по разделам: /help."
        )
