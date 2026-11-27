"""Local JPEG transforms and image persistence on the application data volume."""

from io import BytesIO

from PIL import Image, ImageOps

from form.exceptions import FatalError
from form.llm.model import BoundingBox
from form.settings import Settings


class ImageService:
    def __init__(self, settings: Settings):
        self.max_image_size = settings.max_image_size

    def normalize(self, image: bytes) -> bytes:
        """Apply EXIF orientation and return a JPEG without orientation metadata."""
        with Image.open(BytesIO(image), formats=["JPEG"]) as source:  # noqa: SIM117
            with ImageOps.exif_transpose(source) as normalized:
                return self._jpeg(normalized)

    def rotate_crop(
        self, image: bytes, rotate: int, bounding_box: BoundingBox
    ) -> bytes:
        """Rotate counterclockwise, crop in rotated coordinates, then limit the image size."""
        with (
            Image.open(BytesIO(image), formats=["JPEG"]) as source,
            source.rotate(rotate, expand=True) as rotated,
        ):
            left = max(0, bounding_box.top_left.x)
            top = max(0, bounding_box.top_left.y)
            right = min(rotated.width, bounding_box.bottom_right.x)
            bottom = min(rotated.height, bounding_box.bottom_right.y)
            if right <= left or bottom <= top:
                raise FatalError("Bounding box does not intersect the image")
            with rotated.crop((left, top, right, bottom)) as cropped:
                if max(cropped.size) > self.max_image_size:
                    cropped.thumbnail(
                        (self.max_image_size, self.max_image_size),
                        Image.Resampling.LANCZOS,
                    )
                return self._jpeg(cropped)

    @staticmethod
    def _jpeg(image: Image.Image) -> bytes:
        output = BytesIO()
        with image.convert("RGB") as rgb:
            rgb.save(output, format="JPEG", quality=95, subsampling=0)
        return output.getvalue()
