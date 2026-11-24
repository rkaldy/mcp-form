"""Stateless structured queries through LiteLLM."""

import json
import logging
from base64 import b64encode
from io import BytesIO
from typing import Any

# imagesize is pure Python but does not publish typing metadata or stubs.
import imagesize  # type: ignore[import-untyped]
import litellm
from litellm.types.utils import Choices
from openai import APIError
from pydantic import BaseModel, JsonValue, SecretStr, ValidationError

from form.exceptions import ScanError
from form.llm.instruction import Instruction
from form.llm.model import Form

logger = logging.getLogger(__name__)


class LLM:
    def __init__(self, model: str, api_key: str, config: dict[str, Any]):
        self.model = model
        self.api_key = SecretStr(api_key)
        self.config = config

    @staticmethod
    def _log(event: str, json_data: str):
        if not logger.isEnabledFor(logging.DEBUG):
            return

        def truncate(value: JsonValue) -> JsonValue:
            if isinstance(value, str) and len(value) > 30:
                return f"{value[:30]}... ({len(value)} chars)"
            if isinstance(value, dict):
                return {key: truncate(item) for key, item in value.items()}
            if isinstance(value, list):
                return [truncate(item) for item in value]
            return value

        logger.debug(
            "%s: %s",
            event,
            json.dumps(truncate(json.loads(json_data)), ensure_ascii=False),
        )

    async def query[OutputType: BaseModel](
        self, messages: list[dict], output_type: type[OutputType] | None = None
    ) -> str:
        try:
            result = await litellm.acompletion(
                **self.config,
                model=self.model,
                api_key=self.api_key.get_secret_value(),
                messages=messages,
                response_format=output_type,
                stream=False,
                num_retries=0,
                drop_params=False,
            )
            if (
                not isinstance(result, litellm.ModelResponse)
                or len(result.choices) != 1
            ):
                raise ScanError("Provider returned an unexpected response")
            choice = result.choices[0]
            if (
                not isinstance(choice, Choices)
                or choice.finish_reason != "stop"
                or getattr(choice.message, "refusal", None)
                or not choice.message.content
            ):
                raise ScanError("Provider did not return a complete structured answer")
            return choice.message.content
        except ValidationError as error:
            message = str(
                error.errors(
                    include_input=False, include_context=False, include_url=False
                )
            )
        except APIError as error:
            message = str(error)
        # Raising outside the handler avoids retaining unsafe exception context.
        secret = self.api_key.get_secret_value()
        if secret:
            message = message.replace(secret, "***")
        raise ScanError(message)

    async def health(self) -> bool:
        """Check the LLM is ready to user"""
        await self.query([{"role": "user", "content": "Reply OK."}])
        return True

    async def scan(self, jpg_file: bytes) -> Form:
        """Extract a form from JPEG file contents without changing the image."""
        width, height = imagesize.get(BytesIO(jpg_file), exif_rotation=False)
        if width <= 0 or height <= 0:
            raise ScanError("Could not determine JPEG image dimensions")
        image_url = f"data:image/jpeg;base64,{b64encode(jpg_file).decode('ascii')}"
        messages: list[dict] = [
            {"role": "system", "content": Instruction.SCAN.value},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Extract this form. Image dimensions: {width} × {height} pixels.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                        "detail": "original",
                    },
                ],
            },
        ]
        result = await self.query(messages, Form)
        LLM._log("SCAN", result)
        try:
            return Form.model_validate_json(result, strict=True, extra="forbid")
        except ValidationError as error:
            raise ScanError(
                str(
                    error.errors(
                        include_input=False, include_context=False, include_url=False
                    )
                )
            )
