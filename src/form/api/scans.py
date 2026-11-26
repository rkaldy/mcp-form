from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from form.exceptions import ScanError, UserInputError
from form.llm.model import BoundingBox
from form.model.session import ReviewRequest, ScanResponse
from form.service.dependencies import get_scan_service, get_settings
from form.service.scan import ScanService
from form.settings import Settings

router = APIRouter(prefix="/api/scan")


@router.post(
    "",
    response_model=ScanResponse,
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
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScanResponse:
    """Upload JPEG bytes as an image/jpeg request body."""
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "image/jpeg"
    ):
        raise ScanError("Upload an image/jpeg request body")
    image = bytearray()
    async for chunk in request.stream():
        image.extend(chunk)
        if len(image) > settings.max_upload_size_bytes:
            raise UserInputError(
                f"Obrázek může mít nejvýše {settings.max_upload_size_bytes} bajtů"
            )
    if not image:
        raise ScanError("Image must not be empty")
    return await scan_service.scan(bytes(image))


@router.post("/review", status_code=204)
async def review(
    review: ReviewRequest,
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
):
    await scan_service.review(review)


@router.post("/field", response_class=Response)
async def field_crop(
    session_id: UUID,
    bounding_box: BoundingBox,
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
) -> Response:
    image = await scan_service.field_crop(session_id, bounding_box)
    return Response(
        image, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )
