import json
from contextlib import closing
from datetime import datetime
from sqlite3 import Connection, Row
from uuid import UUID

from form.model.session import Session, SessionStatus


class SessionCRUD:
    @staticmethod
    def _from_row(row: Row) -> Session:
        encoded = row["extracted_data"]
        if not isinstance(encoded, str):
            raise TypeError("Session extracted_data must contain JSON text")
        return Session.model_validate({**row, "extracted_data": json.loads(encoded)})

    def create(self, db_conn: Connection, session: Session):
        db_conn.execute(
            "INSERT INTO sessions (session_id, created_at, extracted_data, status) VALUES (?, ?, ?, ?)",
            (
                str(session.session_id),
                session.created_at.isoformat(),
                json.dumps(session.extracted_data, ensure_ascii=False, allow_nan=False),
                session.status.value,
            ),
        )

    def get(self, db_conn: Connection, session_id: UUID) -> Session | None:
        with closing(
            db_conn.execute(
                "SELECT session_id, created_at, extracted_data, status FROM sessions WHERE session_id = ?",
                (str(session_id),),
            )
        ) as cursor:
            cursor.row_factory = Row
            row = cursor.fetchone()
        return self._from_row(row) if row is not None else None

    def update(self, db_conn: Connection, session: Session):
        db_conn.execute(
            "UPDATE sessions SET extracted_data = ?, status = ? WHERE session_id = ?",
            (
                json.dumps(session.extracted_data, ensure_ascii=False, allow_nan=False),
                session.status.value,
                str(session.session_id),
            ),
        )

    def delete(self, db_conn: Connection, session_id: UUID):
        db_conn.execute("DELETE FROM sessions WHERE session_id = ?", (str(session_id),))

    def expired(self, db_conn: Connection, before: datetime) -> list[Session]:
        """Select finished sessions and sessions created before the UTC cutoff."""
        with closing(
            db_conn.execute(
                "SELECT session_id, created_at, extracted_data, status FROM sessions "
                "WHERE status = ? OR created_at < ?",
                (SessionStatus.FINISHED.value, before.isoformat()),
            )
        ) as cursor:
            cursor.row_factory = Row
            rows = cursor.fetchall()
        return [self._from_row(row) for row in rows]
