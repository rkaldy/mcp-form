import json
from pathlib import Path

import litellm
import pytest

from form.llm.llm import LLM
from form.settings import Settings


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


@pytest.fixture
def scan_jpeg() -> bytes:
    """Load the synthetic JPEG before entering asynchronous test execution."""
    return (Path(__file__).parents[1] / "fixtures" / "blank.jpg").read_bytes()


@pytest.fixture
def llm(settings: Settings) -> LLM:
    return LLM(settings)
