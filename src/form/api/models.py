"""Messages emitted as individual JSON lines by the scan endpoint."""

from uuid import UUID

from pydantic import BaseModel, Field

from form.model.session import SessionStatus, ToReview


class ScanResult(BaseModel):
    session_id: UUID | None
    status: SessionStatus
    reviews: list[ToReview] = Field(default_factory=list)


class ErrorResult(BaseModel):
    error: str
    error_details: str
    fatal: bool
