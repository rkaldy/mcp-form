from collections.abc import AsyncGenerator

import pytest
from fastapi import Request

from form.api.models import ScanResult
from form.api.scan import scan
from form.model.session import SessionStatus
from form.settings import Settings


@pytest.mark.anyio
async def test_scan_passes_uploaded_image_to_service(
    scan_service, processing_service, settings: Settings, jpeg_bytes: bytes
):
    """Emit NORMALIZING on the first iteration, before starting image normalization."""

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": jpeg_bytes, "more_body": False}

    request = Request(
        {"type": "http", "headers": [(b"content-type", b"image/jpeg")]}, receive
    )
    response = await scan(request, settings, scan_service, processing_service)
    stream = aiter(response.body_iterator)
    try:
        chunk = await anext(stream)
        assert isinstance(chunk, str)
        assert ScanResult.model_validate_json(chunk) == ScanResult(
            session_id=None, status=SessionStatus.NORMALIZING
        )
    finally:
        if isinstance(stream, AsyncGenerator):
            await stream.aclose()
