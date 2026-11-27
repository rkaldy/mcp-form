from base64 import b64decode

import litellm
import pytest
from pytest_mock import MockerFixture

from form.exceptions import FatalError
from form.llm.instruction import Instruction
from form.llm.llm import LLM
from form.llm.model import BoundingBox, Coord, FormTransformation
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

    result = await llm.scan(Instruction.SCAN, scan_jpeg, Form)

    assert isinstance(result, Form)
    assert result.static_fields.activity_name.value is None
    assert result.static_fields.activity_name.confidence == 100
    assert result.table_fields == []
    completion.assert_awaited_once()
    assert completion.call_args.kwargs["response_format"] is Form
    messages = completion.call_args.kwargs["messages"]
    assert messages[0] == {"role": "system", "content": Instruction.SCAN.value}
    content = messages[1]["content"]
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
        FatalError, match="Provider did not return a complete structured answer"
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

    with pytest.raises(FatalError, match="Failure with \\*\\*\\*") as caught:
        await llm.health()

    assert caught.value.__context__ is None


@pytest.mark.anyio
async def test_query_returns_provider_text(
    mocker: MockerFixture,
    llm: LLM,
    blank_form_response: litellm.ModelResponse,
):
    """A structured query passes the schema to the provider and returns its raw JSON text."""
    completion = mocker.patch(
        "form.llm.llm.litellm.acompletion", return_value=blank_form_response
    )
    messages = [{"role": "user", "content": "Return a synthetic form."}]

    result = await llm.query(messages, Form)

    assert isinstance(result, str)
    assert Form.model_validate_json(result).table_fields == []
    completion.assert_awaited_once()
    assert completion.call_args.kwargs["messages"] == messages
    assert completion.call_args.kwargs["response_format"] is Form


@pytest.mark.anyio
async def test_scan_accepts_a_different_instruction_and_output_model(
    mocker: MockerFixture,
    llm: LLM,
    scan_jpeg: bytes,
):
    """The generic scan supports localization without assuming the Form schema."""
    transformation = FormTransformation(
        rotate=90,
        crop=BoundingBox(top_left=Coord(x=1, y=2), bottom_right=Coord(x=30, y=16)),
    )
    response = litellm.ModelResponse(
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": transformation.model_dump_json(),
                },
            }
        ]
    )
    completion = mocker.patch("form.llm.llm.litellm.acompletion", return_value=response)

    result = await llm.scan(Instruction.ROTATE_CROP, scan_jpeg, FormTransformation)

    assert result == transformation
    assert isinstance(result, FormTransformation)
    assert completion.call_args.kwargs["response_format"] is FormTransformation
    assert completion.call_args.kwargs["messages"][0] == {
        "role": "system",
        "content": Instruction.ROTATE_CROP.value,
    }
