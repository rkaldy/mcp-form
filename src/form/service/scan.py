"""Orchestrate form extraction, user corrections, processing and session cleanup."""

import json
import logging
import re
from datetime import date
from decimal import Decimal
from typing import get_args
from uuid import UUID

from pydantic import BaseModel, JsonValue, ValidationError

from form.exceptions import FatalError, UserInputError
from form.llm.instruction import Instruction
from form.llm.llm import LLM
from form.llm.model import BoundingBox, FieldType, FormField, FormTransformation, Name
from form.model.form import Form
from form.model.session import (
    ReviewRequest,
    Session,
    SessionStatus,
    ToReview,
)
from form.service.image import ImageService
from form.service.session import SessionService
from form.settings import Settings

logger = logging.getLogger(__name__)


class ScanService:
    def __init__(
        self,
        settings: Settings,
        sessions: SessionService,
        images: ImageService,
        llm: LLM,
    ):
        self.sessions = sessions
        self.images = images
        self.llm = llm
        self.confidence_threshold = settings.confidence_threshold

    def _review_fields(self, model: BaseModel, prefix: str = "") -> list[ToReview]:
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
                result.extend(self._review_fields(field, path))
            elif isinstance(field, list):
                for index, item in enumerate(field):
                    if isinstance(item, BaseModel):
                        result.extend(self._review_fields(item, f"{path}.{index}"))
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
                raise FatalError("Path does not identify a form field")
        if not isinstance(current, dict):
            raise FatalError("Path does not identify a form field")
        return current

    async def normalize(self, scanned_form: bytes) -> UUID:
        session: Session | None = None
        try:
            session = self.sessions.create()
            normalized = self.images.normalize(scanned_form)
            transformation = await self.llm.scan(
                Instruction.ROTATE_CROP, normalized, FormTransformation
            )
            cropped = self.images.rotate_crop(
                normalized, transformation.rotate, transformation.crop
            )
            await self.sessions.save_image(session.session_id, cropped)
            return session.session_id
        except Exception as error:
            if session is not None:
                await self.sessions.delete(session.session_id)
            raise FatalError("Form normalization failed") from error

    async def scan(self, session_id: UUID) -> list[ToReview]:
        session: Session | None = None
        try:
            session = self.sessions.load(
                session_id, SessionStatus.NORMALIZING, SessionStatus.SCANNING
            )
            form_scan = await self.sessions.load_image(session_id)
            form = await self.llm.scan(Instruction.SCAN, form_scan, Form)
            session.extracted_data = json.loads(form.model_dump_json())
            self.sessions.save(session, SessionStatus.REVIEWING)
            return self._review_fields(form)
        except Exception as error:
            if session is not None:
                await self.sessions.delete(session.session_id)
            raise FatalError("Form scanning failed") from error

    async def field_crop(self, session_id: UUID, bounding_box: BoundingBox) -> bytes:
        try:
            self.sessions.load(session_id, SessionStatus.REVIEWING)
            image = await self.sessions.load_image(session_id)
            return self.images.rotate_crop(image, 0, bounding_box)
        except Exception as error:
            await self.sessions.delete(session_id)
            raise FatalError("Field crop failed") from error

    async def review(self, review: ReviewRequest):
        try:
            session = self.sessions.load(review.session_id, SessionStatus.REVIEWING)
            form = Form.model_validate_json(json.dumps(session.extracted_data))
            paths = {correction.path for correction in review.reviews}
            required = {field.path for field in self._review_fields(form)}
            if paths != required:
                raise FatalError(
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
            self.sessions.save(session, SessionStatus.REVIEWING)
        except UserInputError:
            raise
        except Exception as error:
            await self.sessions.delete(review.session_id)
            raise FatalError("Form review failed") from error
