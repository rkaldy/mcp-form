import json
from base64 import b64decode
from pathlib import Path

import litellm
import pytest
from pytest_mock import MockerFixture

from form.exceptions import ScanError
from form.llm.llm import LLM
from form.llm.model import Form


@pytest.fixture
def blank_form_response() -> litellm.ModelResponse:
    """Provide a complete provider response for a blank synthetic form."""
    content = json.dumps(
        {
            "static_fields": {
                name: {"bounding_box": None, "value": None, "confidence": 100}
                for name in (
                    "activity_name",
                    "activity_theme",
                    "date",
                    "lecturer1",
                    "lecturer2",
                    "member_count",
                )
            },
            "table_fields": [],
        }
    )
    return litellm.ModelResponse(
        choices=[
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ]
    )


@pytest.mark.anyio
async def test_scan_sends_original_jpeg_and_its_dimensions(
    mocker: MockerFixture, blank_form_response: litellm.ModelResponse
):
    """Send JPEG bytes with their dimensions and validate the provider response."""
    jpg_file = Path(__file__).with_name("fixtures").joinpath("blank.jpg").read_bytes()
    completion = mocker.patch(
        "form.llm.llm.litellm.acompletion", return_value=blank_form_response
    )

    result = await LLM("test-model", "test-key", {}).scan(jpg_file)

    assert isinstance(result, Form)
    assert result.static_fields.activity_name.value is None
    assert result.static_fields.activity_name.confidence == 100
    assert result.table_fields == []
    completion.assert_awaited_once()
    content = completion.call_args.kwargs["messages"][1]["content"]
    assert "31 × 17 pixels" in content[0]["text"]
    header, encoded_image = content[1]["image_url"]["url"].split(",", 1)
    assert header == "data:image/jpeg;base64"
    assert b64decode(encoded_image) == jpg_file


@pytest.mark.anyio
async def test_health_sends_minimal_prompt_with_configured_options(
    mocker: MockerFixture,
):
    """Check connectivity without sending a form schema or overriding reasoning."""
    response = litellm.ModelResponse(
        choices=[{"message": {"role": "assistant", "content": "OK"}}]
    )
    completion = mocker.patch("form.llm.llm.litellm.acompletion", return_value=response)

    assert (
        await LLM(
            "test-model", "test-key", {"reasoning_effort": "low", "timeout": 120}
        ).health()
        is True
    )

    completion.assert_awaited_once_with(
        model="test-model",
        api_key="test-key",
        messages=[{"role": "user", "content": "Reply OK."}],
        response_format=None,
        reasoning_effort="low",
        timeout=120,
        stream=False,
        num_retries=0,
        drop_params=False,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("content,refusal", [("", None), ("OK", "Refused")])
async def test_health_rejects_missing_or_refused_answers(
    mocker: MockerFixture, content: str, refusal: str | None
):
    """Reject responses that do not establish successful text generation."""
    response = litellm.ModelResponse(
        choices=[
            {"message": {"role": "assistant", "content": content, "refusal": refusal}}
        ]
    )
    mocker.patch("form.llm.llm.litellm.acompletion", return_value=response)

    with pytest.raises(
        ScanError, match="Provider did not return a complete structured answer"
    ):
        await LLM("test-model", "test-key", {}).health()


@pytest.mark.anyio
async def test_health_redacts_api_key_in_provider_errors(mocker: MockerFixture):
    """Translate provider errors without exposing the configured API key."""
    error = litellm.APIError(
        status_code=500,
        message="Failure with test-key",
        llm_provider="test-provider",
        model="test-model",
    )
    mocker.patch("form.llm.llm.litellm.acompletion", side_effect=error)

    with pytest.raises(ScanError, match="Failure with \\*\\*\\*") as caught:
        await LLM("test-model", "test-key", {}).health()

    assert caught.value.__context__ is None
