"""Explicitly enabled Google Sheets write test against a dedicated test spreadsheet."""

import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from form.service.processing import ProcessingService
from form.settings import Settings


@pytest.fixture
def form_data() -> JsonValue:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "form_data.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.mark.anyio
async def test_process(form_data: JsonValue):
    """Write the supplied form, verify the new activity values and remove the inserted row."""
    settings = Settings()
    await ProcessingService(settings).process(form_data)
