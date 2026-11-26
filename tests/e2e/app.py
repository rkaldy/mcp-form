"""Run the real app with isolated storage and deterministic external providers."""

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
from PIL import Image
from pydantic import JsonValue, SecretStr
from sqlalchemy import URL

from form.app import app
from form.llm.llm import LLM, get_llm
from form.llm.model import BoundingBox, Coord, Name
from form.model.form import Form, TableFields
from form.service.dependencies import get_processing_service
from form.service.processing import ProcessingService
from form.settings import Settings, get_settings

storage = TemporaryDirectory(prefix="form-scanner-e2e-")
settings = Settings(
    target_spreadsheet="https://docs.google.com/spreadsheets/d/synthetic-test",
    database_path=Path(storage.name) / "form.sqlite3",
    images_path=Path(storage.name) / "images",
    llm_model="test",
    llm_api_key=SecretStr("synthetic-key"),
    llm_reasoning_effort=None,
    max_upload_size_bytes=20 * 1024 * 1024,
    confidence_threshold=75,
)
form = Form.model_validate_json(
    (Path(__file__).with_name("fixtures") / "blank_form.json").read_text()
)


class FixtureLLM(LLM):
    async def scan(self, jpg_file: bytes) -> Form:
        result = form.model_copy(deep=True)
        with Image.open(BytesIO(jpg_file)) as image:
            needs_review = image.size == (64, 48)
        if needs_review:
            box = BoundingBox(top_left=Coord(x=0, y=0), bottom_right=Coord(x=32, y=24))
            for name, value in [
                ("activity_name", "Testovací aktivita"),
                ("date", date(2026, 11, 8)),
                ("member_count", 2),
            ]:
                field = getattr(result.static_fields, name)
                field.value = value
                field.confidence = 70
                field.bounding_box = box
            result.table_fields = [
                TableFields.model_validate(
                    {
                        name: {
                            "value": {"first_name": "Jana", "surname": "Testová"}
                            if name == "name"
                            else None,
                            "confidence": 70 if name == "name" else 100,
                            "bounding_box": box.model_dump(),
                        }
                        for name in ["name", "child_name", "city", "contact"]
                    }
                )
            ]
        return result


class FixtureProcessingService(ProcessingService):
    async def process(self, data: JsonValue):
        # A successful UI confirmation must follow processing of the corrected values.
        processed = Form.model_validate_json(json.dumps(data))
        if processed.table_fields:
            assert processed.static_fields.activity_name.value == "Opravená aktivita"
            assert processed.static_fields.member_count.value == 3
            assert processed.static_fields.date.value == date(2026, 11, 9)
            assert processed.table_fields[0].name.value == Name(
                first_name="Eva", surname="Ukázková"
            )


config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
config.set_main_option(
    "sqlalchemy.url",
    URL.create("sqlite", database=str(settings.database_path)).render_as_string(
        hide_password=False
    ),
)
command.upgrade(config, "head")
app.dependency_overrides[get_settings] = lambda: settings
app.dependency_overrides[get_llm] = lambda: FixtureLLM(settings)
app.dependency_overrides[get_processing_service] = lambda: FixtureProcessingService(
    settings
)
