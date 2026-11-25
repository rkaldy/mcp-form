from datetime import date
from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from form.llm.llm import LLM
from form.llm.model import Name
from form.model.form import Form
from form.settings import Settings


class ExternalSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="EXTERNAL_", env_file=".env.external")


@pytest.fixture
def settings() -> Settings:
    """Load dedicated EXTERNAL_LLM_* credentials from the environment or .env.external."""
    return ExternalSettings()


@pytest.fixture
def llm(settings: Settings) -> LLM:
    """Use the external settings fixture for live provider calls."""
    if not settings.llm_api_key.get_secret_value():
        pytest.fail("EXTERNAL_LLM_API_KEY must contain a dedicated test API key")
    config: dict[str, str | int] = {"timeout": 120}
    if settings.llm_reasoning_effort is not None:
        config["reasoning_effort"] = settings.llm_reasoning_effort
    return LLM(
        settings.llm_model,
        settings.llm_api_key.get_secret_value(),
        config,
    )


@pytest.fixture
def scan_jpg() -> bytes:
    """Load a synthetic printed form without customer data before asynchronous execution."""
    return (Path(__file__).with_name("fixtures") / "scan_synthetic.jpg").read_bytes()


@pytest.mark.anyio
async def test_llm_health(llm: LLM):
    """Verify the configured live provider returns a healthcheck response."""
    assert await llm.health() is True


@pytest.mark.anyio
async def test_llm_scan(llm: LLM, scan_jpg: bytes):
    """Extract and validate a synthetic form using the explicitly enabled live provider."""
    result = await llm.scan(scan_jpg)

    assert isinstance(result, Form)
    assert result.static_fields.activity_name.value == "Synthetic activity"
    assert result.static_fields.date.value == date(2026, 1, 2)
    assert result.table_fields[0].name.value == Name(
        first_name="Test", surname="Participant"
    )
