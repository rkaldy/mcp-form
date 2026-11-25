from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image, UnidentifiedImageError

from form.llm.model import BoundingBox, Coord
from form.service.image import ImageService
from form.settings import Settings


@pytest.fixture
def jpeg_bytes() -> bytes:
    """Create red and blue halves with EXIF requiring a clockwise quarter turn."""
    output = BytesIO()
    with Image.new("RGB", (40, 20), "red") as image:
        image.paste("blue", (20, 0, 40, 20))
        exif = image.getexif()
        exif[274] = 6
        image.save(output, format="JPEG", quality=100, subsampling=0, exif=exif)
    return output.getvalue()


@pytest.fixture
def image_service(settings: Settings) -> ImageService:
    return ImageService(settings)


def test_normalize_and_crop_locally(image_service: ImageService, jpeg_bytes: bytes):
    """Normalize EXIF once, then crop upright pixels locally without storage calls."""
    normalized = image_service.normalize(jpeg_bytes)
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 40)
        assert image.getexif().get(274, 1) == 1
        pixel = image.getpixel((10, 10))
        assert isinstance(pixel, tuple) and pixel[0] > 245
    cropped = image_service.crop(
        normalized,
        BoundingBox(top_left=Coord(x=-4, y=20), bottom_right=Coord(x=40, y=50)),
    )
    with Image.open(BytesIO(cropped)) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 20)
        pixel = image.getpixel((10, 10))
        assert isinstance(pixel, tuple)
        assert pixel[0] < 10 and pixel[1] < 10 and pixel[2] > 245


@pytest.mark.anyio
async def test_save_and_load_uuid_without_changing_image(
    image_service: ImageService, jpeg_bytes: bytes
):
    """Use canonical UUID keys and preserve stored JPEG bytes and EXIF unchanged."""
    image_id = uuid4()
    await image_service.save(image_id, jpeg_bytes)
    assert await image_service.load(image_id) == jpeg_bytes


@pytest.mark.anyio
async def test_load_missing_image(image_service: ImageService):
    """Report an absent image as FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        await image_service.load(uuid4())


def test_reject_invalid_image(image_service: ImageService):
    """Pillow rejects invalid JPEG data before attempting a transform."""
    with pytest.raises(UnidentifiedImageError):
        image_service.normalize(b"invalid JPEG")
