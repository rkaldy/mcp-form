"""Run the real app with isolated storage and deterministic external providers."""

from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
from pydantic import JsonValue, SecretStr
from sqlalchemy import URL

from form.app import app
from form.llm.llm import LLM, get_llm
from form.model.form import Form
from form.service.dependencies import get_processing_service
from form.service.processing import ProcessingService
from form.settings import Settings, get_settings

storage = TemporaryDirectory(prefix="form-scanner-e2e-")
settings = Settings(
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
        return form.model_copy(deep=True)


class FixtureProcessingService(ProcessingService):
    async def process(self, data: JsonValue):
        pass


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
app.dependency_overrides[get_processing_service] = FixtureProcessingService
