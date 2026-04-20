# Architecture Note

## Intent

This repository is a local-first, single-user MVP. The first shipped value is digest summaries from selected Telegram sources. Memory, reply suggestions, reminders, and provider expansion are planned but intentionally not implemented in this skeleton.

## Module responsibilities

- `apps/` contains runnable entrypoints only.
- `bot/` contains aiogram routing and thin Telegram handlers.
- `worker/` contains background-job registration points.
- `services/` contains application logic that handlers and entrypoints call.
- `config/` contains shared environment-driven settings.
- `storage/` contains SQLAlchemy bootstrap and session setup.
- `models/` is reserved for ORM models.
- `schemas/` contains typed payloads and transport models.
- `adapters/` defines reusable adapter boundaries.
- `telegram_bot/`, `business/`, and `fullaccess/` hold adapter implementations for future access modes.
- `migrations/` contains Alembic configuration.

## Boundary rules

- Keep Telegram handlers thin. They should validate/update transport details and call services.
- Keep product logic out of aiogram handlers.
- Keep adapter boundaries explicit so future business/full-access modes do not leak into bot handlers.
- Prefer additive modules over growing monolith files.

## Near-term evolution

- Add source-selection and digest orchestration under `services/` plus adapter-backed fetchers.
- Add ORM models and Alembic revisions when the first persistent entities are defined.
- Add reminder, memory, and reply modules as separate services instead of attaching them to handlers.
