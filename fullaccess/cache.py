from __future__ import annotations

from pathlib import Path


CACHE_DIR_NAME = "fullaccess-cache"


def cache_root_from_session(session_file: Path) -> Path:
    return session_file.expanduser().parent / CACHE_DIR_NAME


def avatar_base_path(session_file: Path, telegram_chat_id: int) -> Path:
    return cache_root_from_session(session_file) / "avatars" / str(telegram_chat_id)


def media_preview_base_path(
    session_file: Path,
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
) -> Path:
    return (
        cache_root_from_session(session_file)
        / "media"
        / str(telegram_chat_id)
        / str(telegram_message_id)
    )


def find_cached_variant(base_path: Path) -> Path | None:
    if not base_path.parent.exists():
        return None

    candidates = sorted(
        path
        for path in base_path.parent.glob(f"{base_path.name}.*")
        if path.is_file()
    )
    return candidates[0] if candidates else None


def clear_cached_variants(base_path: Path) -> None:
    if not base_path.parent.exists():
        return

    for path in base_path.parent.glob(f"{base_path.name}.*"):
        if path.is_file():
            path.unlink(missing_ok=True)
