from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from uuid import uuid4

import pytest

from form.crud.session import SessionCRUD
from form.model.session import Session, SessionStatus


@pytest.fixture
def expiration_sessions(
    db_conn: Connection,
) -> tuple[datetime, dict[tuple[SessionStatus, int], Session]]:
    """Create every status before, exactly at, and after a fixed expiration cutoff."""
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)
    sessions = {}
    crud = SessionCRUD()
    for status in [
        SessionStatus.NORMALIZING,
        SessionStatus.SCANNING,
        SessionStatus.FINISHED,
    ]:
        for offset in (-1, 0, 1):
            session = Session(
                session_id=uuid4(),
                created_at=cutoff + timedelta(seconds=offset),
                extracted_data={"synthetic": [status.value, offset]},
                status=status,
            )
            crud.create(db_conn, session)
            sessions[status, offset] = session
    return cutoff, sessions


def test_expired_selects_finished_or_strictly_older_sessions(
    db_conn: Connection,
    expiration_sessions: tuple[datetime, dict[tuple[SessionStatus, int], Session]],
):
    """Select FINISHED at any age and other statuses only strictly before the cutoff."""
    cutoff, sessions = expiration_sessions
    expected = [
        sessions[SessionStatus.NORMALIZING, -1],
        sessions[SessionStatus.SCANNING, -1],
        *(sessions[SessionStatus.FINISHED, offset] for offset in (-1, 0, 1)),
    ]

    expired = SessionCRUD().expired(db_conn, cutoff)

    assert {session.session_id: session for session in expired} == {
        session.session_id: session for session in expected
    }


def test_expired_returns_empty_when_no_sessions_exist(db_conn: Connection):
    """Return no cleanup candidates from an empty database."""
    cutoff = datetime(2026, 1, 2, tzinfo=UTC)

    assert SessionCRUD().expired(db_conn, cutoff) == []
