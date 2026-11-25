from base64 import b64decode

import litellm
import pytest
from pytest_mock import MockerFixture

from form.exceptions import ScanError
from form.llm.llm import LLM
from form.model.form import Form
from form.settings import Settings


@pytest.mark.anyio
async def test_scan_sends_original_jpeg_and_its_dimensions(
    mocker: MockerFixture,
    blank_form_response: litellm.ModelResponse,
    scan_jpeg: bytes,
    llm: LLM,
):
    """Send JPEG bytes with their dimensions and validate the provider response."""
    completion = mocker.patch(
        "form.llm.llm.litellm.acompletion", return_value=blank_form_response
    )

    result = await llm.scan(scan_jpeg)

    assert isinstance(result, Form)
    assert result.static_fields.activity_name.value is None
    assert result.static_fields.activity_name.confidence == 100
    assert result.table_fields == []
    completion.assert_awaited_once()
    content = completion.call_args.kwargs["messages"][1]["content"]
    assert "31 × 17 pixels" in content[0]["text"]
    header, encoded_image = content[1]["image_url"]["url"].split(",", 1)
    assert header == "data:image/jpeg;base64"
    assert b64decode(encoded_image) == scan_jpeg


@pytest.mark.anyio
async def test_health_sends_minimal_prompt_with_configured_options(
    mocker: MockerFixture,
    llm: LLM,
    settings: Settings,
):
    """Check connectivity without sending a form schema or overriding reasoning."""
    response = litellm.ModelResponse(
        choices=[{"message": {"role": "assistant", "content": "OK"}}]
    )
    completion = mocker.patch("form.llm.llm.litellm.acompletion", return_value=response)
    llm.config["reasoning_effort"] = "low"

    assert await llm.health() is True

    completion.assert_awaited_once_with(
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value(),
        messages=[{"role": "user", "content": "Reply OK."}],
        response_format=None,
        reasoning_effort="low",
        timeout=settings.llm_timeout,
        stream=False,
        num_retries=0,
        drop_params=False,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("content,refusal", [("", None), ("OK", "Refused")])
async def test_health_rejects_missing_or_refused_answers(
    mocker: MockerFixture, content: str, refusal: str | None, llm: LLM
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
        await llm.health()


@pytest.mark.anyio
async def test_health_redacts_api_key_in_provider_errors(
    mocker: MockerFixture, llm: LLM
):
    """Translate provider errors without exposing the configured API key."""
    error = litellm.APIError(
        status_code=500,
        message=f"Failure with {llm.api_key.get_secret_value()}",
        llm_provider="test-provider",
        model=llm.model,
    )
    mocker.patch("form.llm.llm.litellm.acompletion", side_effect=error)

    with pytest.raises(ScanError, match="Failure with \\*\\*\\*") as caught:
        await llm.health()

    assert caught.value.__context__ is None
