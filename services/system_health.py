from __future__ import annotations

from dataclasses import dataclass

from services.system_readiness import OperationalReport


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ok_items: tuple[str, ...]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SystemHealthService:
    def build_report(self, readiness: OperationalReport) -> DoctorReport:
        facts = readiness.facts
        ok_items: list[str] = ["База данных отвечает."]

        if facts.schema_revision is not None:
            ok_items.append(f"Миграции применены: {facts.schema_revision}.")
        if facts.owner_chat_id is not None:
            ok_items.append(f"owner chat известен: {facts.owner_chat_id}.")
        if facts.active_sources > 0:
            ok_items.append(f"Активных источников: {facts.active_sources}.")
        if facts.total_messages > 0:
            ok_items.append(f"В БД сохранено сообщений: {facts.total_messages}.")
        if facts.reminders_worker_ready:
            ok_items.append("Worker path reminder_delivery подключён.")

        for layer in readiness.layers:
            if layer.ready:
                ok_items.append(f"{layer.title}: {layer.detail}")

        warnings = readiness.warnings
        if not warnings:
            warnings = ("Критичных проблем не найдено.",)

        next_steps = readiness.next_steps
        if not next_steps:
            next_steps = ("Критичных проблем не найдено. Можно использовать /digest_now, /reply и /reminders_scan.",)

        return DoctorReport(
            ok_items=tuple(_dedupe(ok_items)),
            warnings=warnings,
            next_steps=next_steps,
        )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
