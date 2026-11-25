from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, JsonValue

from form.llm.model import BoundingBox, FieldType


class SessionStatus(Enum):
    SCANNING = "scanning"
    REVIEWING = "reviewing"
    PROCESSING = "processing"
    FINISHED = "finished"


class Session(BaseModel):
    session_id: UUID
    created_at: datetime
    extracted_data: JsonValue
    status: SessionStatus


class ToReview(BaseModel):
    type: FieldType
    path: str
    label: str
    value: JsonValue
    bounding_box: BoundingBox | None


class ScanResponse(BaseModel):
    session_id: UUID
    reviews: list[ToReview]


class Review(BaseModel):
    path: str
    value: JsonValue


class ReviewRequest(BaseModel):
    session_id: UUID
    reviews: list[Review]
