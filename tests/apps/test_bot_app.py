from config.settings import Settings
from apps.bot.app import build_bot_runtime


def test_build_bot_runtime_requires_telegram_token(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    settings = Settings()

    try:
        build_bot_runtime(settings)
    except RuntimeError as error:
        assert "TELEGRAM_BOT_TOKEN" in str(error)
    else:
        raise AssertionError("build_bot_runtime should require TELEGRAM_BOT_TOKEN")


def test_build_bot_runtime_creates_dispatcher(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")

    settings = Settings()
    runtime = build_bot_runtime(settings)

    assert runtime.dispatcher is not None
    assert runtime.settings.telegram_bot_token == "123456:TEST_TOKEN"
