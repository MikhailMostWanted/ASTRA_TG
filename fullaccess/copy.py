from __future__ import annotations


LOCAL_LOGIN_COMMAND = "astratg fullaccess login"


def local_login_instruction_lines() -> tuple[str, ...]:
    return (
        "Открой Astra Desktop и перейди во вкладку «Full-access».",
        "Запроси код прямо в интерфейсе и введи его там же.",
        f"CLI остаётся только резервным fallback: {LOCAL_LOGIN_COMMAND}.",
    )
