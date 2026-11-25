import json

import pytest
from pydantic import JsonValue
from pytest_mock import MockerFixture

from form.database.d1 import D1Binding
from form.llm.llm import LLM
from form.model.form import Form
from form.service.image import ImageService
from form.service.processing import ProcessingService
from form.service.scan import ScanService
from form.settings import Settings


@pytest.fixture
def form() -> Form:
    """Provide synthetic fields including dates, integer and structured name values."""

    def field(value: JsonValue, confidence: int = 100) -> dict[str, JsonValue]:
        return {"value": value, "confidence": confidence, "bounding_box": None}

    return Form.model_validate_json(
        json.dumps(
            {
                "static_fields": {
                    "activity_name": field("Synthetic activity"),
                    "activity_theme": field(None),
                    "date": field("2026-01-02"),
                    "lecturer1": field(None),
                    "lecturer2": field(None),
                    "member_count": field(2, 74),
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


@pytest.fixture
def scan_service(
    db_binding: D1Binding, image_service, llm, processing_service, settings: Settings
) -> ScanService:
    return ScanService(db_binding, image_service, llm, processing_service, settings)
