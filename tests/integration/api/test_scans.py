import json
from collections.abc import AsyncIterator
from datetime import date
from io import BytesIO
from pathlib import Path
from sqlite3 import Connection

import httpx
import pytest
from PIL import Image
from pytest_mock import MockerFixture

from form.app import app
from form.crud.session import SessionCRUD
from form.database.database import Database
from form.llm.model import FieldType, Name
from form.model.form import Form
from form.model.session import (
    Review,
    ReviewRequest,
    ScanResponse,
    ToReview,
)
from form.service.dependencies import get_scan_service
from form.service.image import ImageService
from form.service.scan import ScanService
from form.settings import Settings


@pytest.fixture
def form_data() -> Form:
    """Load fields read from scan.jpg, with exactly two deliberately uncertain values."""
    return Form.model_validate_json(
        (Path(__file__).parents[1] / "fixtures" / "form_data.json").read_text()
    )


@pytest.fixture
def form_image() -> bytes:
    """Load the original uploaded form before asynchronous test execution."""
    return (Path(__file__).parents[1] / "fixtures" / "form.jpg").read_bytes()


def jpeg_pixels(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(BytesIO(data)) as image, image.convert("RGB") as rgb:
        return rgb.size, rgb.tobytes()


@pytest.fixture
def expected_crops() -> dict[str, tuple[tuple[int, int], bytes]]:
    """Read fixed references cropped independently from the normalized scan."""
    fixtures = Path(__file__).parents[1] / "fixtures"
    return {
        "static_fields.date": jpeg_pixels((fixtures / "field_date.jpg").read_bytes()),
        "table_fields.4.name": jpeg_pixels((fixtures / "field_name.jpg").read_bytes()),
    }


@pytest.fixture
def image_service(settings: Settings) -> ImageService:
    return ImageService(settings)


@pytest.fixture
def processing_service(mocker: MockerFixture):
    return mocker.patch(
        "form.service.dependencies.ProcessingService", autospec=True
    ).return_value


@pytest.fixture
def scan_service(
    mocker: MockerFixture,
    settings: Settings,
    database: Database,
    form_data: Form,
    image_service: ImageService,
    processing_service,
):
    llm = mocker.patch("form.service.dependencies.LLM", autospec=True).return_value
    llm.scan.return_value = form_data

    app.dependency_overrides[get_scan_service] = lambda: ScanService(
        database, image_service, llm, processing_service, settings
    )
    yield
    app.dependency_overrides.pop(get_scan_service)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
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
    db_conn: Connection,
    settings: Settings,
    scan_service,
    image_service,
    processing_service,
):
    """Scan via HTTP, review two real image crops, process corrections and remove session."""
    response = await client.post(
        "/api/scan", content=form_image, headers={"Content-Type": "image/jpeg"}
    )
    assert response.status_code == 200
    scan = ScanResponse.model_validate_json(response.content)
    try:
        assert scan.reviews == [
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

        for field in scan.reviews:
            assert field.bounding_box is not None
            crop = await client.post(
                "/api/scan/field",
                params={"session_id": str(scan.session_id)},
                json=field.bounding_box.model_dump(mode="json"),
            )
            assert crop.status_code == 200
            assert crop.headers["content-type"] == "image/jpeg"
            assert jpeg_pixels(crop.content) == expected_crops[field.path]

        corrected = form_data.model_copy(deep=True)
        corrected.static_fields.date.value = date(2026, 11, 9)
        corrected.table_fields[4].name.value = Name(
            first_name="Ivana", surname="Šmardová"
        )
        review = ReviewRequest(
            session_id=scan.session_id,
            reviews=[
                Review(path="static_fields.date", value="2026-11-09"),
                Review(
                    path="table_fields.4.name",
                    value={"first_name": "Ivana", "surname": "Šmardová"},
                ),
            ],
        )
        response = await client.post(
            "/api/scan/review", json=review.model_dump(mode="json")
        )
        assert response.status_code == 204
        processing_service.process.assert_awaited_once_with(
            json.loads(corrected.model_dump_json())
        )

        assert SessionCRUD().get(db_conn, scan.session_id) is None
        with pytest.raises(FileNotFoundError):
            await image_service.load(scan.session_id)
    finally:
        await image_service.delete(scan.session_id)
