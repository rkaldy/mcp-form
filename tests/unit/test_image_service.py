from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import Request
from PIL import Image, UnidentifiedImageError
from pytest_mock import MockerFixture

from form.llm.model import BoundingBox, Coord
from form.service.dependencies import get_image_service
from form.service.image import ImageService, R2Bucket, R2Object


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
def bucket(mocker: MockerFixture, jpeg_bytes: bytes) -> Mock:
    bucket = mocker.create_autospec(R2Bucket, instance=True)
    image = mocker.create_autospec(R2Object, instance=True)
    image.arrayBuffer.return_value = memoryview(jpeg_bytes)
    bucket.get.return_value = image
    return bucket


def test_normalize_and_crop_locally(bucket: Mock, jpeg_bytes: bytes):
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
async def test_save_and_load_uuid_without_changing_image(
    bucket: Mock, jpeg_bytes: bytes
):
    """Use canonical UUID keys and preserve stored JPEG bytes and EXIF unchanged."""
    service = ImageService(bucket)
    image_id = uuid4()
    await service.save(image_id, jpeg_bytes)
    bucket.put.assert_awaited_once_with(str(image_id), jpeg_bytes)
    assert await service.load(image_id) == jpeg_bytes
    bucket.get.assert_awaited_once_with(str(image_id))


@pytest.mark.anyio
async def test_load_missing_image(bucket: Mock):
    """Report an absent R2 object as FileNotFoundError."""
    bucket.get.return_value = None
    with pytest.raises(FileNotFoundError):
        await ImageService(bucket).load(uuid4())


def test_reject_invalid_image(bucket: Mock):
    """Pillow rejects invalid JPEG data before attempting a transform."""
    with pytest.raises(UnidentifiedImageError):
        ImageService(bucket).normalize(b"invalid JPEG")


@pytest.mark.anyio
async def test_dependency_uses_configured_r2_bucket(bucket: Mock, jpeg_bytes: bytes):
    """The dependency passes the Workers binding to the service without another backend."""
    request = Request({"type": "http", "env": SimpleNamespace(FORM_IMAGES=bucket)})
    image_id = uuid4()
    assert await get_image_service(request).load(image_id) == jpeg_bytes
    bucket.get.assert_awaited_once_with(str(image_id))


def test_dependency_requires_workers():
    """Explain the runtime requirement if the binding environment is missing."""
    with pytest.raises(RuntimeError, match="pywrangler dev"):
        get_image_service(Request({"type": "http"}))
