from pathlib import Path
from uuid import uuid4

import pytest

from form.service.image import ImageService, R2Bucket


@pytest.fixture
def jpeg_bytes() -> bytes:
    """Use the synthetic JPEG fixture without accessing a customer document."""
    return (Path(__file__).parents[1] / "unit" / "fixtures" / "blank.jpg").read_bytes()


@pytest.mark.anyio
async def test_save_load_delete_against_local_r2(
    local_r2_bucket: R2Bucket, jpeg_bytes: bytes
):
    """Round-trip exact JPEG bytes through local R2, overwrite, delete and verify absence."""
    service = ImageService(local_r2_bucket)
    image_id = uuid4()
    try:
        with pytest.raises(FileNotFoundError):
            await service.load(image_id)
        await service.save(image_id, jpeg_bytes)
        assert await service.load(image_id) == jpeg_bytes
        # The raw UUID key must contain the original bytes, not encoded image data.
        stored = await local_r2_bucket.get(str(image_id))
        assert stored is not None
        assert bytes(await stored.arrayBuffer()) == jpeg_bytes
        await service.save(image_id, jpeg_bytes + b"\x00replacement")
        assert await service.load(image_id) == jpeg_bytes + b"\x00replacement"
        await service.delete(image_id)
        with pytest.raises(FileNotFoundError):
            await service.load(image_id)
        await service.delete(image_id)
    finally:
        await service.delete(image_id)
