"""Local JPEG transforms and image persistence through the R2 binding."""

from io import BytesIO
from typing import Protocol
from uuid import UUID

from PIL import Image, ImageOps

from form.exceptions import UserInputError
from form.llm.model import BoundingBox


class R2Object(Protocol):
    async def arrayBuffer(self) -> memoryview: ...


class R2Bucket(Protocol):
    async def put(self, key: str, data: bytes) -> object: ...
    async def get(self, key: str) -> R2Object | None: ...
    async def delete(self, key: str): ...


class ImageService:
    def __init__(self, bucket: R2Bucket):
        self.bucket = bucket

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
        """Store the supplied bytes unchanged under the UUID's canonical string."""
        await self.bucket.put(str(image_id), image)

    async def load(self, image_id: UUID) -> bytes:
        """Load stored bytes; raise FileNotFoundError when the UUID is absent."""
        image = await self.bucket.get(str(image_id))
        if image is None:
            raise FileNotFoundError("Image not found")
        return bytes(await image.arrayBuffer())

    async def delete(self, image_id: UUID):
        """Delete the stored image under the UUID's canonical string."""
        await self.bucket.delete(str(image_id))

    @staticmethod
    def _jpeg(image: Image.Image) -> bytes:
        output = BytesIO()
        with image.convert("RGB") as rgb:
            rgb.save(output, format="JPEG", quality=95, subsampling=0)
        return output.getvalue()
