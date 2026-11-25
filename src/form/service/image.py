"""Local JPEG transforms and image persistence on the application data volume."""

from io import BytesIO
from uuid import UUID

from anyio import Path
from PIL import Image, ImageOps

from form.exceptions import UserInputError
from form.llm.model import BoundingBox
from form.settings import Settings


class ImageService:
    def __init__(self, settings: Settings):
        self.directory = Path(settings.images_path)

    def normalize(self, image: bytes) -> bytes:
        """Apply EXIF orientation and return a JPEG without orientation metadata."""
        with Image.open(BytesIO(image), formats=["JPEG"]) as source:  # noqa: SIM117
            with ImageOps.exif_transpose(source) as normalized:
                return self._jpeg(normalized)

    def crop(self, image: bytes, bounding_box: BoundingBox) -> bytes:
        """Crop in supplied-image coordinates; normalize camera photos beforehand.

        The bottom-right corner is exclusive. Clip partially overlapping boxes;
        reject empty, reversed, or nonintersecting boxes with UserInputError.
        """
        with Image.open(BytesIO(image), formats=["JPEG"]) as source:
            left = max(0, bounding_box.top_left.x)
            top = max(0, bounding_box.top_left.y)
            right = min(source.width, bounding_box.bottom_right.x)
            bottom = min(source.height, bounding_box.bottom_right.y)
            if right <= left or bottom <= top:
                raise UserInputError("Bounding box does not intersect the image")
            with source.crop((left, top, right, bottom)) as cropped:
                return self._jpeg(cropped)

    async def save(self, image_id: UUID, image: bytes):
        await self.directory.mkdir(parents=True, exist_ok=True)
        await self._image_file(image_id).write_bytes(image)

    async def load(self, image_id: UUID) -> bytes:
        return await self._image_file(image_id).read_bytes()

    async def delete(self, image_id: UUID):
        await self._image_file(image_id).unlink(missing_ok=True)

    def _image_file(self, image_id: UUID) -> Path:
        return self.directory / f"{image_id}.jpg"

    @staticmethod
    def _jpeg(image: Image.Image) -> bytes:
        output = BytesIO()
        with image.convert("RGB") as rgb:
            rgb.save(output, format="JPEG", quality=95, subsampling=0)
        return output.getvalue()
