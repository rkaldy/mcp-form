from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from form.crud.session import SessionCRUD
from form.database.d1 import D1Connection
from form.model.session import Session, SessionStatus


@pytest.fixture
async def expiration_sessions(
    db_connection: D1Connection,
) -> tuple[datetime, dict[tuple[SessionStatus, int], Session]]:
    """Create every status before, exactly at, and after a fixed expiration cutoff."""
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    sessions = {}
    crud = SessionCRUD()
    for status in SessionStatus:
        for offset in (-1, 0, 1):
            session = Session(
                session_id=uuid4(),
                created_at=cutoff + timedelta(seconds=offset),
                extracted_data={"synthetic": [status.value, offset]},
                status=status,
            )
            await crud.create(db_connection, session)
            sessions[status, offset] = session
    return cutoff, sessions


@pytest.mark.anyio
async def test_expired_selects_finished_or_strictly_older_sessions(
    db_connection: D1Connection,
    expiration_sessions: tuple[datetime, dict[tuple[SessionStatus, int], Session]],
):
    """Select FINISHED at any age and other statuses only strictly before the cutoff."""
    cutoff, sessions = expiration_sessions
    expected = [
        sessions[SessionStatus.SCANNING, -1],
        sessions[SessionStatus.REVIEWING, -1],
        sessions[SessionStatus.PROCESSING, -1],
        *(sessions[SessionStatus.FINISHED, offset] for offset in (-1, 0, 1)),
    ]

    expired = await SessionCRUD().expired(db_connection, cutoff)

    assert {session.session_id: session for session in expired} == {
        session.session_id: session for session in expected
    }


@pytest.mark.anyio
async def test_expired_returns_empty_when_no_sessions_exist(
    db_connection: D1Connection,
):
    """Return no cleanup candidates from an empty database."""
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)

    assert await SessionCRUD().expired(db_connection, cutoff) == []
