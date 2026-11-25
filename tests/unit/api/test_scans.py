from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pytest_mock import MockerFixture

from form.app import app
from form.model.session import ScanResponse
from form.service.dependencies import get_scan_service, get_settings
from form.service.scan import ScanService
from form.settings import Settings


@pytest.fixture
def scan_service(mocker: MockerFixture):
    service = mocker.create_autospec(ScanService, instance=True)
    service.scan.return_value = ScanResponse(session_id=uuid4(), reviews=[])
    return service


@pytest.fixture
def jpeg_bytes() -> bytes:
    """Load a synthetic JPEG before entering asynchronous test execution."""
    return (Path(__file__).parents[1] / "fixtures" / "blank.jpg").read_bytes()


@pytest.fixture
async def client(scan_service, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Use the actual route with a mocked service and isolated upload configuration."""
    app.dependency_overrides[get_scan_service] = lambda: scan_service
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_scan_service)
        app.dependency_overrides.pop(get_settings)


@pytest.mark.anyio
async def test_scan_passes_uploaded_image_to_service(
    client: httpx.AsyncClient, scan_service, jpeg_bytes: bytes
):
    """An HTTP upload passes the exact request image bytes to ScanService.scan."""
    response = await client.post(
        "/api/scan", content=jpeg_bytes, headers={"Content-Type": "image/jpeg"}
    )

    assert response.status_code == 200
    scan_service.scan.assert_awaited_once_with(jpeg_bytes)
