from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from form.llm.model import BoundingBox, Coord
from form.service.image import ImageService
from form.settings import Settings


@pytest.fixture
def image_service(settings: Settings) -> ImageService:
    return ImageService(settings)


def test_normalize_applies_exif_orientation(
    image_service: ImageService, jpeg_bytes: bytes
):
    """Normalize EXIF orientation independently of explicit rotation and cropping."""
    normalized = image_service.normalize(jpeg_bytes)
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 40)
        assert image.getexif().get(274, 1) == 1
        pixel = image.getpixel((10, 10))
        assert isinstance(pixel, tuple) and pixel[0] > 245


def test_reject_invalid_image(image_service: ImageService):
    """Pillow rejects invalid JPEG data before attempting a transform."""
    with pytest.raises(UnidentifiedImageError):
        image_service.rotate_crop(
            b"invalid JPEG",
            0,
            BoundingBox(top_left=Coord(x=0, y=0), bottom_right=Coord(x=10, y=10)),
        )


@pytest.mark.parametrize(
    ("rotate", "top_left", "bottom_right"),
    [
        (0, (20, -4), (70, 40)),
        (90, (-4, -4), (20, 20)),
        (180, (-4, -4), (20, 40)),
        (270, (0, 20), (30, 60)),
        (-90, (0, 20), (30, 60)),
    ],
)
def test_rotate_crop_rotates_before_clipping_and_cropping(
    image_service: ImageService,
    jpeg_bytes: bytes,
    rotate: int,
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
):
    """Crop the blue half in rotated coordinates, clipping to the expanded dimensions."""
    cropped = image_service.rotate_crop(
        jpeg_bytes,
        rotate,
        BoundingBox(
            top_left=Coord(x=top_left[0], y=top_left[1]),
            bottom_right=Coord(x=bottom_right[0], y=bottom_right[1]),
        ),
    )
    with Image.open(BytesIO(cropped)) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 20)
        pixel = image.getpixel((10, 10))
        assert isinstance(pixel, tuple)
        assert pixel[0] < 10 and pixel[1] < 10 and pixel[2] > 245
