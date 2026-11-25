from io import BytesIO

import pytest
from PIL import Image
from pytest_mock import MockerFixture

from form.service.image import R2Bucket, R2Object


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
def bucket(mocker: MockerFixture, jpeg_bytes: bytes):
    bucket = mocker.create_autospec(R2Bucket, instance=True)
    image = mocker.create_autospec(R2Object, instance=True)
    image.arrayBuffer.return_value = memoryview(jpeg_bytes)
    bucket.get.return_value = image
    return bucket
