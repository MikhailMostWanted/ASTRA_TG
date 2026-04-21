from dataclasses import dataclass
from datetime import datetime, timezone

from services.reminder_extractor import ReminderExtractor


@dataclass(slots=True)
class FakeMessage:
    id: int
    chat_id: int
    sender_name: str | None
    sent_at: datetime
    raw_text: str
    normalized_text: str


def test_extractor_detects_explicit_reminder_with_relative_date_and_time() -> None:
    extractor = ReminderExtractor()
    message = FakeMessage(
        id=101,
        chat_id=77,
        sender_name="Анна",
        sent_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
        raw_text="Не забудь завтра в 09:30 отправить финальный договор клиенту",
        normalized_text="не забудь завтра в 09:30 отправить финальный договор клиенту",
    )

    candidate = extractor.extract(message, now=datetime(2026, 4, 20, 10, 5, tzinfo=timezone.utc))

    assert candidate is not None
    assert candidate.title == "Отправить финальный договор клиенту"
    assert candidate.due_at == datetime(2026, 4, 21, 9, 30, tzinfo=timezone.utc)
    assert candidate.suggested_remind_at == datetime(2026, 4, 21, 8, 30, tzinfo=timezone.utc)
    assert any("не забудь" in reason.lower() for reason in candidate.reasons)
    assert any("09:30" in reason for reason in candidate.reasons)
    assert candidate.confidence >= 0.8


def test_extractor_ignores_noise_without_action_markers() -> None:
    extractor = ReminderExtractor()
    message = FakeMessage(
        id=102,
        chat_id=77,
        sender_name="Анна",
        sent_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
        raw_text="Ок, увидел, спасибо. Тогда позже просто обсудим.",
        normalized_text="ок, увидел, спасибо. тогда позже просто обсудим.",
    )

    candidate = extractor.extract(message, now=datetime(2026, 4, 20, 10, 5, tzinfo=timezone.utc))

    assert candidate is None
