import pytest

from config.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_tests_from_local_dotenv():
    original_env_file = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original_env_file
