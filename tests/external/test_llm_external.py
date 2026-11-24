import logging
from datetime import date
from pathlib import Path
from pprint import pprint
from typing import Any

import pytest

from form.llm.llm import LLM
from form.llm.model import Form, Name, StaticFields
from form.settings import Settings


@pytest.fixture
def llm(caplog: pytest.LogCaptureFixture) -> LLM:
    """Load the current application settings from the environment and .env."""
    settings = Settings()
    if not settings.llm_api_key.get_secret_value():
        pytest.fail("LLM_API_KEY must contain an API key")
    caplog.set_level(logging.DEBUG, logger="form.llm.llm")
    config: dict[str, Any] = {"timeout": 120}
    if settings.llm_reasoning_effort is not None:
        config["reasoning_effort"] = settings.llm_reasoning_effort
    return LLM(
        settings.llm_model,
        settings.llm_api_key.get_secret_value(),
        config,
    )


@pytest.fixture
def scan_jpg() -> bytes:
    """Load the explicitly supplied scan image before asynchronous test execution."""
    return Path(__file__).with_name("scan.jpg").read_bytes()


@pytest.mark.anyio
async def test_llm_health(llm: LLM):
    """Verify the configured live provider returns a healthcheck response."""
    assert await llm.health() is True


@pytest.mark.anyio
async def test_llm_scan(llm: LLM, scan_jpg: bytes):
    """Extract and validate a real structured form from scan.jpg."""
    result = await llm.scan(scan_jpg)

    assert isinstance(result, Form)
    assert "Lískáček svépomocná skupina" in result.static_fields.activity_name.value
    assert result.static_fields.date.value == date(2026, 11, 9)
    assert result.table_fields[0].name.value == Name(first_name="Katarína", surname="Garlíková")
    pprint(result)