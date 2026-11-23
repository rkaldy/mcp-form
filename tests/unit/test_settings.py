import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from form.settings import Settings


def test_settings_load_process_environment_without_constructor_values(
    mocker: MockerFixture,
):
    """Load all settings automatically from environment variables without .env."""
    mocker.patch.dict(Settings.model_config, {"env_file": None})
    mocker.patch.dict(
        os.environ,
        {
            "LLM_MODEL": "environment-model",
            "LLM_API_KEY": "synthetic-env-key",
            "LLM_REASONING_EFFORT": "high",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.llm_model == "environment-model"
    assert settings.llm_api_key.get_secret_value() == "synthetic-env-key"
    assert settings.llm_reasoning_effort == "high"


@pytest.fixture
def dotenv_file(tmp_path: Path, mocker: MockerFixture) -> Path:
    """Isolate configuration sources from the developer's environment and secrets."""
    path = tmp_path / ".env"
    path.write_text(
        "LLM_MODEL=dotenv-model\nLLM_API_KEY=synthetic-dotenv-key\n"
        "LLM_REASONING_EFFORT=low\n",
        encoding="utf-8",
    )
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch.dict(Settings.model_config, {"env_file": path})
    return path


def test_settings_load_dotenv(dotenv_file: Path):
    """Load settings from .env and hide the API key in representations."""
    settings = Settings()

    assert settings.llm_model == "dotenv-model"
    assert settings.llm_api_key.get_secret_value() == "synthetic-dotenv-key"
    assert settings.llm_reasoning_effort == "low"
    assert "synthetic-dotenv-key" not in repr(settings)
    assert "synthetic-dotenv-key" not in settings.model_dump_json()
