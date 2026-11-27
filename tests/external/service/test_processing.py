"""Explicitly enabled Google Sheets write test against a dedicated test spreadsheet."""

import json
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

import pytest
from pydantic import JsonValue

from form.crud.session import SessionCRUD
from form.model.session import Session, SessionStatus
from form.service.processing import ProcessingService
from form.service.session import SessionService
from form.settings import Settings


@pytest.fixture
def form_data() -> JsonValue:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "form_data.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.mark.anyio
async def test_process(
    form_data: JsonValue, session_service: SessionService, db_conn: Connection
):
    """Write the supplied form, verify the new activity values and remove the inserted row."""
    settings = Settings()
    session = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        extracted_data=form_data,
        status=SessionStatus.REVIEWING,
    )
    SessionCRUD().create(db_conn, session)
    await ProcessingService(settings, session_service).process(session.session_id)
