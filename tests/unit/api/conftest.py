from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pytest_mock import MockerFixture

from form.app import app
from form.service.dependencies import (
    get_processing_service,
    get_scan_service,
    get_settings,
)
from form.service.scan import ScanService
from form.settings import Settings


@pytest.fixture
def scan_service(mocker: MockerFixture):
    service = mocker.create_autospec(ScanService, instance=True)
    service.normalize.return_value = uuid4()
    service.scan.return_value = []
    return service


@pytest.fixture
def jpeg_bytes() -> bytes:
    """Load a synthetic JPEG before entering asynchronous test execution."""
    return (Path(__file__).parents[1] / "fixtures" / "blank.jpg").read_bytes()


@pytest.fixture
async def client(
    scan_service, processing_service, settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    """Use the actual route with mocked processing and isolated upload configuration."""
    app.dependency_overrides[get_processing_service] = lambda: processing_service
    app.dependency_overrides[get_scan_service] = lambda: scan_service
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_processing_service)
        app.dependency_overrides.pop(get_scan_service)
        app.dependency_overrides.pop(get_settings)
