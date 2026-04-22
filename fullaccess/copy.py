from __future__ import annotations


LOCAL_LOGIN_COMMAND = "astratg fullaccess login"


def local_login_instruction_lines() -> tuple[str, ...]:
    return (
        "Открой терминал.",
        f"Запусти: {LOCAL_LOGIN_COMMAND}",
        "После входа вернись в бота и нажми «Обновить».",
    )
