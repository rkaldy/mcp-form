import json
from collections.abc import AsyncIterator
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pytest_mock import MockerFixture
from starlette.types import Receive, Scope, Send

from form.app import app
from form.crud.session import SessionCRUD
from form.database.d1 import D1Binding, D1Connection
from form.llm.model import FieldType, Name
from form.model.form import Form
from form.model.session import (
    Review,
    ReviewRequest,
    ScanResponse,
    ToReview,
)
from form.service.image import R2Bucket
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
def llm(mocker: MockerFixture, form_data: Form):
    llm = mocker.patch("form.service.dependencies.LLM", autospec=True).return_value
    llm.scan.return_value = form_data
    return llm


@pytest.fixture
def processing_service(mocker: MockerFixture):
    return mocker.patch(
        "form.service.dependencies.ProcessingService", autospec=True
    ).return_value


@pytest.fixture
async def client(
    db_binding: D1Binding,
    local_r2_bucket: R2Bucket,
    settings: Settings,
    llm,
    processing_service,
) -> AsyncIterator[httpx.AsyncClient]:
    """Exercise production dependency wiring using real SQLite and local Wrangler R2."""
    env = SimpleNamespace(
        DB=db_binding,
        FORM_IMAGES=local_r2_bucket,
        **{name.upper(): value for name, value in settings.model_dump().items()},
    )

    async def application(scope: Scope, receive: Receive, send: Send):
        scope["env"] = env
        await app(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.anyio
async def test_scan_happy_path(
    client: httpx.AsyncClient,
    form_image: bytes,
    form_data: Form,
    expected_crops: dict[str, tuple[tuple[int, int], bytes]],
    db_connection: D1Connection,
    local_r2_bucket: R2Bucket,
    llm,
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

        assert await SessionCRUD().get(db_connection, scan.session_id) is None
        assert await local_r2_bucket.get(str(scan.session_id)) is None
    finally:
        await local_r2_bucket.delete(str(scan.session_id))
