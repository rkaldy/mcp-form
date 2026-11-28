from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from form.api.models import ErrorResult, ScanResult
from form.api.stream import StreamServer
from form.exceptions import FatalError, UserInputError
from form.llm.model import BoundingBox
from form.model.session import ReviewRequest, SessionStatus
from form.service.dependencies import (
    get_processing_service,
    get_scan_service,
    get_settings,
)
from form.service.processing import ProcessingService
from form.service.scan import ScanService
from form.settings import Settings

router = APIRouter(prefix="/api/scan")


@router.post(
    "",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "NDJSON stream of ScanResult or ErrorResult messages",
            "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def scan(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
    processing_service: Annotated[ProcessingService, Depends(get_processing_service)],
) -> StreamingResponse:
    # Read the upload before StreamingResponse starts listening for client disconnects.
    image = bytearray()
    upload_error: FatalError | UserInputError | None = None
    try:
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "image/jpeg"
        ):
            raise FatalError("Upload an image/jpeg request body")
        async for chunk in request.stream():
            image.extend(chunk)
            if len(image) > settings.max_upload_size_bytes:
                raise UserInputError(
                    f"Obrázek může mít nejvýše {settings.max_upload_size_bytes} bajtů"
                )
        if not image:
            raise FatalError("Image must not be empty")
    except (FatalError, UserInputError) as error:
        upload_error = error

    async def generator() -> AsyncIterator[ScanResult | ErrorResult]:
        if upload_error is not None:
            raise upload_error
        yield ScanResult(session_id=None, status=SessionStatus.NORMALIZING)
        session_id = await scan_service.normalize(bytes(image))
        yield ScanResult(session_id=session_id, status=SessionStatus.SCANNING)
        reviews = await scan_service.scan(session_id)
        if reviews:
            yield ScanResult(
                session_id=session_id,
                status=SessionStatus.REVIEWING,
                reviews=reviews,
            )
            return
        yield ScanResult(session_id=session_id, status=SessionStatus.PROCESSING)
        await processing_service.process(session_id)
        yield ScanResult(session_id=session_id, status=SessionStatus.FINISHED)

    return StreamServer(generator)


@router.post("/review", status_code=204)
async def review(
    review: ReviewRequest,
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
    processing_service: Annotated[ProcessingService, Depends(get_processing_service)],
):
    async def generator() -> AsyncIterator[ScanResult | ErrorResult]:
        await scan_service.review(review)
        yield ScanResult(session_id=review.session_id, status=SessionStatus.PROCESSING)
        await processing_service.process(review.session_id)
        yield ScanResult(session_id=review.session_id, status=SessionStatus.FINISHED)

    return StreamServer(generator)


@router.post("/field", response_class=Response)
async def field(
    session_id: UUID,
    bounding_box: BoundingBox,
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
) -> Response:
    image = await scan_service.field_crop(session_id, bounding_box)
    return Response(
        image, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )
