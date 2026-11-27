from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from uuid import uuid4

import pytest
from freezegun import freeze_time

from form.crud.session import SessionCRUD
from form.model.session import Session, SessionStatus
from form.service.session import SessionService


@pytest.mark.anyio
async def test_save_and_load_uuid_without_changing_image(
    session_service: SessionService, jpeg_bytes: bytes
):
    """Use canonical UUID keys and preserve stored JPEG bytes and EXIF unchanged."""
    image_id = uuid4()
    await session_service.save_image(image_id, jpeg_bytes)
    assert await session_service.load_image(image_id) == jpeg_bytes
    await session_service.delete(image_id)


@pytest.mark.anyio
async def test_load_missing_image(session_service: SessionService):
    """Report an absent image as FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        await session_service.load_image(uuid4())


@pytest.mark.anyio
@freeze_time("2026-01-02T00:00:00+00:00", real_asyncio=True)
async def test_clean_finished_and_old_sessions(
    session_service: SessionService,
    db_conn: Connection,
):
    """Clean FINISHED and every status older than 24 hours, while retaining recent reviews."""
    recent = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        status=SessionStatus.REVIEWING,
        extracted_data=None,
    )
    SessionCRUD().create(db_conn, recent)
    removed = []
    for status in SessionStatus:
        session = Session(
            session_id=uuid4(),
            created_at=datetime.now(UTC) - timedelta(hours=25),
            status=status,
            extracted_data=None,
        )
        SessionCRUD().create(db_conn, session)
        removed.append(session.session_id)
    finished = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        status=SessionStatus.FINISHED,
        extracted_data=None,
    )
    SessionCRUD().create(db_conn, finished)
    removed.append(finished.session_id)
    for session_id in removed + [recent.session_id]:
        await session_service.save_image(session_id, b"stored-jpeg")
    await session_service.clean()
    for session_id in removed:
        with pytest.raises(FileNotFoundError):
            await session_service.load_image(session_id)
    assert await session_service.load_image(recent.session_id) == b"stored-jpeg"
    assert SessionCRUD().get(db_conn, recent.session_id) == recent
    assert len(db_conn.execute("SELECT session_id FROM sessions").fetchall()) == 1
    await session_service.delete(recent.session_id)
