import json
from collections.abc import AsyncIterator
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from PIL import Image
from pytest_mock import MockerFixture

from form.api.models import ScanResult
from form.app import app
from form.database.database import Database
from form.llm.instruction import Instruction
from form.llm.llm import LLM
from form.llm.model import (
    BoundingBox,
    Coord,
    FieldType,
    FormTransformation,
    LLMBase,
    Name,
)
from form.model.form import Form
from form.model.session import Review, ReviewRequest, SessionStatus, ToReview
from form.service.dependencies import (
    get_processing_service,
    get_scan_service,
    get_settings,
)
from form.service.image import ImageService
from form.service.scan import ScanService
from form.service.session import SessionService
from form.settings import Settings


@pytest.fixture
def scan_settings(settings: Settings, request: pytest.FixtureRequest) -> Settings:
    return settings.model_copy(update=getattr(request, "param", {}))


@pytest.fixture
def form_data() -> Form:
    return Form.model_validate_json(
        (Path(__file__).parents[1] / "fixtures" / "form_data.json").read_text()
    )


@pytest.fixture
def form_transformation() -> FormTransformation:
    return FormTransformation(
        rotate=0,
        crop=BoundingBox(
            top_left=Coord(x=100, y=100), bottom_right=Coord(x=1636, y=1252)
        ),
    )


@pytest.fixture
def form_image() -> bytes:
    return (Path(__file__).parents[1] / "fixtures" / "form.jpg").read_bytes()


def jpeg_pixels(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(BytesIO(data)) as image, image.convert("RGB") as rgb:
        return rgb.size, rgb.tobytes()


@pytest.fixture
def image_service(settings: Settings) -> ImageService:
    return ImageService(settings)


@pytest.fixture
def llm(
    mocker: MockerFixture, form_transformation: FormTransformation, form_data: Form
):
    def scan(
        instruction: Instruction, _image: bytes, _output_type: type[LLMBase]
    ) -> LLMBase:
        if instruction == Instruction.ROTATE_CROP:
            return form_transformation
        else:
            return form_data

    llm = mocker.create_autospec(LLM, instance=True)
    llm.scan.side_effect = scan
    return llm


@pytest.fixture
def processing_service(mocker: MockerFixture):
    return mocker.patch(
        "form.service.dependencies.ProcessingService", autospec=True
    ).return_value


@pytest.fixture
def session_service(
    settings: Settings, database: Database, tmp_path: Path
) -> SessionService:
    return SessionService(
        settings.model_copy(update={"images_path": tmp_path / "images"}), database
    )


@pytest.fixture
def dependencies(
    scan_settings: Settings,
    session_service: SessionService,
    image_service: ImageService,
    processing_service,
    llm,
):
    app.dependency_overrides[get_settings] = lambda: scan_settings
    app.dependency_overrides[get_scan_service] = lambda: ScanService(
        scan_settings, session_service, image_service, llm
    )
    app.dependency_overrides[get_processing_service] = lambda: processing_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings)
        app.dependency_overrides.pop(get_processing_service)
        app.dependency_overrides.pop(get_scan_service)


@pytest.fixture
def processed_forms(processing_service, session_service: SessionService) -> list[Form]:
    """Capture the persisted extraction visible to the processing boundary."""
    forms: list[Form] = []

    async def process(session_id: UUID):
        stored = session_service.load(session_id, SessionStatus.REVIEWING)
        forms.append(Form.model_validate_json(json.dumps(stored.extracted_data)))

    processing_service.process.side_effect = process
    return forms


@pytest.fixture
def expected_crops() -> dict[str, tuple[tuple[int, int], bytes]]:
    fixtures = Path(__file__).parents[1] / "fixtures"
    return {
        "static_fields.date": jpeg_pixels((fixtures / "field_date.jpg").read_bytes()),
        "table_fields.4.name": jpeg_pixels((fixtures / "field_name.jpg").read_bytes()),
    }


@pytest.fixture
async def client(dependencies) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.anyio
async def test_scan_happy_path(
    client: httpx.AsyncClient,
    form_image: bytes,
    form_data: Form,
    expected_crops: dict[str, tuple[tuple[int, int], bytes]],
    processed_forms: list[Form],
    processing_service,
):
    """Scan a form, verify both uncertain fields and crops, then process persisted corrections."""
    async with client.stream(
        "POST", "/api/scan", content=form_image, headers={"Content-Type": "image/jpeg"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-ndjson"
        events = [
            ScanResult.model_validate_json(line)
            async for line in response.aiter_lines()
        ]

    assert [event.status for event in events] == [
        SessionStatus.NORMALIZING,
        SessionStatus.SCANNING,
        SessionStatus.REVIEWING,
    ]
    session_id = events[1].session_id
    assert session_id is not None
    assert events[0].session_id is None
    assert events[2].session_id == session_id
    assert events[0].reviews == events[1].reviews == []
    assert events[2].reviews == [
        ToReview(
            type=FieldType.DATE,
            path="static_fields.date",
            label="Datum realizace (od - do)",
            value="2026-11-08",
            bounding_box=form_data.static_fields.date.bounding_box,
        ),
        ToReview(
            type=FieldType.NAME,
            path="table_fields.4.name",
            label="Jméno a příjmení účastníka",
            value={"first_name": "Ivana", "surname": "Pitarová"},
            bounding_box=form_data.table_fields[4].name.bounding_box,
        ),
    ]
    processing_service.process.assert_not_awaited()

    for field in events[2].reviews:
        assert field.bounding_box is not None
        crop = await client.post(
            "/api/scan/field",
            params={"session_id": str(session_id)},
            json=field.bounding_box.model_dump(mode="json"),
        )
        assert crop.status_code == 200
        assert crop.headers["content-type"] == "image/jpeg"
        assert jpeg_pixels(crop.content) == expected_crops[field.path]

    review = ReviewRequest(
        session_id=session_id,
        reviews=[
            Review(path="static_fields.date", value="2026-11-09"),
            Review(
                path="table_fields.4.name",
                value={"first_name": "Ivana", "surname": "Šmardová"},
            ),
        ],
    )
    async with client.stream(
        "POST", "/api/scan/review", json=review.model_dump(mode="json")
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-ndjson"
        events = [
            ScanResult.model_validate_json(line)
            async for line in response.aiter_lines()
        ]
    assert events == [
        ScanResult(session_id=session_id, status=SessionStatus.PROCESSING),
        ScanResult(session_id=session_id, status=SessionStatus.FINISHED),
    ]
    processing_service.process.assert_awaited_once_with(session_id)
    corrected = form_data.model_copy(deep=True)
    corrected.static_fields.date.value = date(2026, 11, 9)
    corrected.table_fields[4].name.value = Name(first_name="Ivana", surname="Šmardová")
    assert processed_forms == [corrected]


@pytest.mark.anyio
@pytest.mark.parametrize("scan_settings", [{"confidence_threshold": 50}], indirect=True)
async def test_scan_happy_path_without_review(
    client: httpx.AsyncClient,
    form_image: bytes,
    form_data: Form,
    processed_forms: list[Form],
    processing_service,
):
    """Process an accepted extraction directly, without requesting user corrections."""
    async with client.stream(
        "POST", "/api/scan", content=form_image, headers={"Content-Type": "image/jpeg"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-ndjson"
        events = [
            ScanResult.model_validate_json(line)
            async for line in response.aiter_lines()
        ]

    assert len(events) == 4
    session_id = events[1].session_id
    assert session_id is not None
    assert events == [
        ScanResult(session_id=None, status=SessionStatus.NORMALIZING),
        ScanResult(session_id=session_id, status=SessionStatus.SCANNING),
        ScanResult(session_id=session_id, status=SessionStatus.PROCESSING),
        ScanResult(session_id=session_id, status=SessionStatus.FINISHED),
    ]
    processing_service.process.assert_awaited_once_with(session_id)
    assert processed_forms == [form_data]
