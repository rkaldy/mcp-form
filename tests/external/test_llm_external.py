"""Opt-in live provider tests using the application's current configuration."""

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from form.llm.llm import LLM
from form.llm.model import Form
from form.settings import Settings

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("RUN_LLM_EXTERNAL_TESTS") != "1",
        reason="Set RUN_LLM_EXTERNAL_TESTS=1 to enable paid LLM calls",
    ),
]


@pytest.fixture
def external_llm(caplog: pytest.LogCaptureFixture) -> LLM:
    """Load the current application settings from the environment and .env."""
    settings = Settings()
    if not settings.llm_api_key.get_secret_value():
        pytest.fail("LLM_API_KEY must contain an API key")
    caplog.set_level(logging.WARNING, logger="form.llm.llm")
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


async def test_llm_health(external_llm: LLM):
    """Verify the configured live provider returns a healthcheck response."""
    assert await external_llm.health() is True


async def test_llm_scan(external_llm: LLM, scan_jpg: bytes):
    """Extract and validate a real structured form from scan.jpg."""
    result = await external_llm.scan(scan_jpg)

    assert isinstance(result, Form)
    values = result.static_fields.model_dump()
    assert any(field["value"] is not None for field in values.values()) or bool(
        result.table_fields
    ), "No form values were extracted from scan.jpg"
