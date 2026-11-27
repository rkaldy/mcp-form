import json
import logging

import litellm
import pytest
from pytest_mock import MockerFixture

from form.llm.instruction import Instruction
from form.llm.llm import LLM
from form.model.form import Form


@pytest.fixture
def long_form_response(
    blank_form_response: litellm.ModelResponse,
) -> litellm.ModelResponse:
    """Provide a valid synthetic form with long strings in the header and nested rows."""
    response = blank_form_response.model_dump()
    data = json.loads(response["choices"][0]["message"]["content"])
    data["static_fields"]["activity_name"]["value"] = "ž" * 31
    data["static_fields"]["activity_theme"]["value"] = "a" * 30
    data["table_fields"] = [
        {
            "name": {
                "value": {"first_name": "Test", "surname": "b" * 45},
                "confidence": 100,
                "bounding_box": None,
            },
            "child_name": {"value": None, "confidence": 100, "bounding_box": None},
            "city": {"value": "Testov", "confidence": 100, "bounding_box": None},
            "contact": {"value": None, "confidence": 100, "bounding_box": None},
        }
    ]
    response["choices"][0]["message"]["content"] = json.dumps(data)
    return litellm.ModelResponse.model_validate(response)


@pytest.mark.anyio
async def test_scan_truncates_debug_log_without_modifying_result(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    long_form_response: litellm.ModelResponse,
    scan_jpeg: bytes,
    llm: LLM,
):
    """Public scan logs abbreviated nested text while returning the complete extraction."""
    mocker.patch("form.llm.llm.litellm.acompletion", return_value=long_form_response)
    with caplog.at_level(logging.DEBUG, logger="form.llm.llm"):
        result = await llm.scan(Instruction.SCAN, scan_jpeg, Form)

    records = [record for record in caplog.records if record.name == "form.llm.llm"]
    assert len(records) == 1
    event, payload = records[0].getMessage().split(": ", 1)
    logged = json.loads(payload)
    assert event == Instruction.SCAN.code
    assert (
        logged["static_fields"]["activity_name"]["value"] == "ž" * 30 + "... (31 chars)"
    )
    assert logged["static_fields"]["activity_theme"]["value"] == "a" * 30
    assert (
        logged["table_fields"][0]["name"]["value"]["surname"]
        == "b" * 30 + "... (45 chars)"
    )
    assert result.static_fields.activity_name.value == "ž" * 31
    assert result.table_fields[0].name.value is not None
    assert result.table_fields[0].name.value.surname == "b" * 45


@pytest.mark.anyio
async def test_scan_does_not_log_form_without_debug(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    long_form_response: litellm.ModelResponse,
    scan_jpeg: bytes,
    llm: LLM,
):
    """A normal scan produces no form payload log when debug logging is disabled."""
    mocker.patch("form.llm.llm.litellm.acompletion", return_value=long_form_response)
    with caplog.at_level(logging.INFO, logger="form.llm.llm"):
        await llm.scan(Instruction.SCAN, scan_jpeg, Form)
    assert not [record for record in caplog.records if record.name == "form.llm.llm"]
