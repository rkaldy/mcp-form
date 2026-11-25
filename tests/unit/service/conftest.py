from io import BytesIO

import pytest
from PIL import Image


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
