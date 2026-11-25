from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image, UnidentifiedImageError

from form.llm.model import BoundingBox, Coord
from form.service.image import ImageService


def test_normalize_and_crop_locally(bucket, jpeg_bytes: bytes):
    """Normalize EXIF once, then crop upright pixels locally without storage calls."""
    service = ImageService(bucket)
    normalized = service.normalize(jpeg_bytes)
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 40)
        assert image.getexif().get(274, 1) == 1
        pixel = image.getpixel((10, 10))
        assert isinstance(pixel, tuple) and pixel[0] > 245
    cropped = service.crop(
        normalized,
        BoundingBox(top_left=Coord(x=-4, y=20), bottom_right=Coord(x=40, y=50)),
    )
    with Image.open(BytesIO(cropped)) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 20)
        pixel = image.getpixel((10, 10))
        assert isinstance(pixel, tuple)
        assert pixel[0] < 10 and pixel[1] < 10 and pixel[2] > 245
    bucket.put.assert_not_awaited()
    bucket.get.assert_not_awaited()


@pytest.mark.anyio
async def test_save_and_load_uuid_without_changing_image(bucket, jpeg_bytes: bytes):
    """Use canonical UUID keys and preserve stored JPEG bytes and EXIF unchanged."""
    service = ImageService(bucket)
    image_id = uuid4()
    await service.save(image_id, jpeg_bytes)
    assert await service.load(image_id) == jpeg_bytes
    bucket.put.assert_awaited_once_with(str(image_id), jpeg_bytes)
    bucket.get.assert_awaited_once_with(str(image_id))


@pytest.mark.anyio
async def test_load_missing_image(bucket):
    """Report an absent R2 object as FileNotFoundError."""
    bucket.get.return_value = None
    with pytest.raises(FileNotFoundError):
        await ImageService(bucket).load(uuid4())


def test_reject_invalid_image(bucket):
    """Pillow rejects invalid JPEG data before attempting a transform."""
    with pytest.raises(UnidentifiedImageError):
        ImageService(bucket).normalize(b"invalid JPEG")
