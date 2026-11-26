"""Orchestrate form extraction, user corrections, processing and session cleanup."""

import json
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import get_args
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue, ValidationError

from form.crud.session import SessionCRUD
from form.database.database import Database
from form.exceptions import ProcessingError, ScanError, UserInputError
from form.llm.llm import LLM
from form.llm.model import BoundingBox, FieldType, FormField, Name
from form.model.form import Form
from form.model.session import (
    ReviewRequest,
    ScanResponse,
    Session,
    SessionStatus,
    ToReview,
)
from form.service.image import ImageService
from form.service.processing import ProcessingService
from form.settings import Settings

logger = logging.getLogger(__name__)


class ScanService:
    def __init__(
        self,
        database: Database,
        images: ImageService,
        llm: LLM,
        processing: ProcessingService,
        settings: Settings,
    ):
        self.database = database
        self.images = images
        self.llm = llm
        self.processing = processing
        self.confidence_threshold = settings.confidence_threshold
        self.session_ttl = settings.session_ttl
        self.crud = SessionCRUD()

    def review_fields(self, model: BaseModel, prefix: str = "") -> list[ToReview]:
        result = []
        for name, definition in type(model).model_fields.items():
            field = getattr(model, name)
            path = f"{prefix}.{name}" if prefix else name
            if isinstance(field, FormField):
                if field.confidence < self.confidence_threshold or (
                    name in ("activity_name", "date") and field.value is None
                ):
                    field_type = FieldType.STRING
                    for value_type in get_args(
                        type(field).model_fields["value"].annotation
                    ):
                        if value_type is int:
                            field_type = FieldType.INTEGER
                        elif value_type is bool:
                            field_type = FieldType.BOOLEAN
                        elif value_type is date:
                            field_type = FieldType.DATE
                        elif value_type is Decimal:
                            field_type = FieldType.DECIMAL
                        elif value_type is Name:
                            field_type = FieldType.NAME
                    label = re.search(r"'([^']+)'", definition.description or "")
                    result.append(
                        ToReview(
                            type=field_type,
                            path=path,
                            label=label.group(1) if label else name,
                            value=field.model_dump(mode="json")["value"],
                            bounding_box=field.bounding_box,
                        )
                    )
            elif isinstance(field, BaseModel):
                result.extend(self.review_fields(field, path))
            elif isinstance(field, list):
                for index, item in enumerate(field):
                    if isinstance(item, BaseModel):
                        result.extend(self.review_fields(item, f"{path}.{index}"))
        return result

    @staticmethod
    def _field(data: JsonValue, path: str) -> dict[str, JsonValue]:
        """Resolve a field path previously checked against the extraction model."""
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current[part]
            elif isinstance(current, list):
                current = current[int(part)]
            else:
                raise ScanError("Path does not identify a form field")
        if not isinstance(current, dict):
            raise ScanError("Path does not identify a form field")
        return current

    async def get(self, session_id: UUID) -> Session:
        with self.database.connect() as connection:
            session = self.crud.get(connection, session_id)
        if session is None:
            raise ScanError("Session not found")
        return session

    async def delete(self, session_id: UUID):
        try:
            await self.images.delete(session_id)
            with self.database.connect() as connection:
                self.crud.delete(connection, session_id)
        except Exception:  # noqa: BLE001 -- best-effort cleanup must neither mask the original error nor expose provider payloads.
            logger.error(
                "Session cleanup failed", extra={"session_id": str(session_id)}
            )

    async def scan(self, scanned_form: bytes) -> ScanResponse:
        session: Session | None = None
        try:
            image = self.images.normalize(scanned_form)
            session = Session(
                session_id=uuid4(),
                created_at=datetime.now(UTC),
                extracted_data=None,
                status=SessionStatus.SCANNING,
            )
            with self.database.connect() as conn:
                self.crud.create(conn, session)
            await self.images.save(session.session_id, image)
            form = await self.llm.scan(image)
            session.extracted_data = json.loads(form.model_dump_json())
            session.status = SessionStatus.REVIEWING
            with self.database.connect() as conn:
                self.crud.update(conn, session)
            reviews = self.review_fields(form)
        except Exception as error:
            if session is not None:
                await self.delete(session.session_id)
            raise ScanError("Form scanning failed") from error
        if not reviews:
            await self.process(session)
        return ScanResponse(session_id=session.session_id, reviews=reviews)

    async def field_crop(self, session_id: UUID, bounding_box: BoundingBox) -> bytes:
        try:
            await self.get(session_id)
            image = await self.images.load(session_id)
            return self.images.crop(image, bounding_box)
        except Exception as error:
            await self.delete(session_id)
            raise ScanError("Field crop failed") from error

    async def review(self, review: ReviewRequest):
        try:
            session = await self.get(review.session_id)
            if session.status != SessionStatus.REVIEWING:
                raise ScanError("Session is not awaiting review")
            form = Form.model_validate_json(json.dumps(session.extracted_data))
            paths = {correction.path for correction in review.reviews}
            required = {field.path for field in self.review_fields(form)}
            if paths != required:
                raise ScanError(
                    "Submit valid field paths and confirm every requested field once"
                )
            for correction in review.reviews:
                self._field(session.extracted_data, correction.path)["value"] = (
                    correction.value
                )
            try:
                Form.model_validate_json(
                    json.dumps(session.extracted_data), strict=True
                )
            except ValidationError as error:
                raise UserInputError("Chybně zadaná hodnota") from error
        except UserInputError:
            raise
        except Exception as error:
            await self.delete(review.session_id)
            raise ScanError("Form review failed") from error
        await self.process(session)

    async def process(self, session: Session):
        """Persist each lifecycle state; cleanup failures never fail successful processing."""
        try:
            session.status = SessionStatus.PROCESSING
            with self.database.connect() as conn:
                self.crud.update(conn, session)
            await self.processing.process(session.extracted_data)
            session.status = SessionStatus.FINISHED
            with self.database.connect() as conn:
                self.crud.update(conn, session)
        except UserInputError:
            raise
        except ProcessingError as error:
            await self.delete(session.session_id)
            raise ScanError("Error in target system") from error
        except Exception as error:
            await self.delete(session.session_id)
            raise ScanError("Form processing failed") from error
        await self.delete(session.session_id)

    async def clean(self):
        """Best-effort cleanup of finished or expired sessions; future cron entrypoint."""
        try:
            with self.database.connect() as conn:
                sessions = self.crud.expired(conn, datetime.now(UTC) - self.session_ttl)
        except Exception:  # noqa: BLE001 -- cron cleanup failures are logged without returning errors or provider payloads.
            logger.error("Could not select sessions for cleanup")
            return
        for session in sessions:
            await self.delete(session.session_id)
