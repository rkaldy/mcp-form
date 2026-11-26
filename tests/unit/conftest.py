import json

import pytest
from pydantic import JsonValue
from pytest_mock import MockerFixture

from form.llm.llm import LLM
from form.model.form import Form
from form.service.image import ImageService
from form.service.processing import ProcessingService


@pytest.fixture
def form() -> Form:
    """Provide synthetic fields including an uncertain date and structured name."""

    def field(value: JsonValue, confidence: int = 100) -> dict[str, JsonValue]:
        return {"value": value, "confidence": confidence, "bounding_box": None}

    return Form.model_validate_json(
        json.dumps(
            {
                "static_fields": {
                    "activity_name": field("Synthetic activity"),
                    "activity_theme": field(None),
                    "date": field("2026-01-02", 74),
                    "lecturer1": field(None),
                    "lecturer2": field(None),
                },
                "table_fields": [
                    {
                        "name": field({"first_name": "Test", "surname": "Person"}, 40),
                        "child_name": field(None),
                        "city": field(None),
                        "contact": field(None),
                    }
                ],
            }
        )
    )


@pytest.fixture
def image_service(mocker: MockerFixture):
    images = mocker.create_autospec(ImageService, instance=True)
    images.normalize.return_value = b"normalized-jpeg"
    images.load.return_value = b"stored-jpeg"
    images.crop.return_value = b"cropped-jpeg"
    return images


@pytest.fixture
def llm(mocker: MockerFixture, form: Form):
    llm = mocker.create_autospec(LLM, instance=True)
    llm.scan.return_value = form
    return llm


@pytest.fixture
def processing_service(mocker: MockerFixture):
    return mocker.create_autospec(ProcessingService, instance=True)
