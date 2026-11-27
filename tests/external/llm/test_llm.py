from datetime import date
from pathlib import Path
from pprint import pprint
from uuid import UUID

import pytest
from pydantic_settings import SettingsConfigDict

from form.llm.instruction import Instruction
from form.llm.llm import LLM
from form.llm.model import FormTransformation, Name
from form.model.form import Form
from form.service.image import ImageService
from form.service.session import SessionService
from form.settings import Settings


class ExternalSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="EXTERNAL_", env_file=".env.external")


@pytest.fixture
def llm() -> LLM:
    """Use local .env for LLM credentials"""
    return LLM(Settings())


@pytest.fixture
def scan_jpg() -> bytes:
    return (Path(__file__).parents[1] / "fixtures" / "scan_synthetic.jpg").read_bytes()


@pytest.fixture
def raw_jpg() -> bytes:
    return (Path(__file__).parents[1] / "fixtures" / "raw.jpg").read_bytes()


@pytest.mark.anyio
async def test_llm_health(llm: LLM):
    """Verify the configured live provider returns a healthcheck response."""
    assert await llm.health() is True


@pytest.mark.anyio
async def test_llm_normalize(llm: LLM, raw_jpg: bytes, session_service: SessionService):
    """Computes rotation and cropping of the form photo, so the final image contains only the form in basic position"""
    images = ImageService(Settings())
    normalized = images.normalize(raw_jpg)
    result = await llm.scan(Instruction.ROTATE_CROP, normalized, FormTransformation)
    pprint(result)
    cropped = images.rotate_crop(normalized, result.rotate, result.crop)
    try:
        await session_service.save_image(UUID(int=0), cropped)
    finally:
        await session_service.delete(UUID(int=0))


@pytest.mark.anyio
async def test_llm_scan(llm: LLM, scan_jpg: bytes):
    """Extract and validate a synthetic form using the explicitly enabled live provider."""
    result = await llm.scan(Instruction.SCAN, scan_jpg, Form)

    assert isinstance(result, Form)
    assert result.static_fields.activity_name.value == "Synthetic activity"
    assert result.static_fields.date.value == date(2026, 1, 2)
    assert result.table_fields[0].name.value == Name(
        first_name="Test", surname="Participant"
    )
