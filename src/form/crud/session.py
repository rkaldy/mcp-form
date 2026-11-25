"""Session persistence through parameterized D1 SQL."""

import json
from datetime import datetime
from uuid import UUID

from form.database.d1 import D1Connection, Row
from form.model.session import Session, SessionStatus


class SessionCRUD:
    @staticmethod
    def _from_row(row: Row) -> Session:
        encoded = row["extracted_data"]
        if not isinstance(encoded, str):
            raise TypeError("Session extracted_data must contain JSON text")
        return Session.model_validate({**row, "extracted_data": json.loads(encoded)})

    async def create(self, connection: D1Connection, session: Session):
        await connection.execute(
            "INSERT INTO sessions (session_id, created_at, extracted_data, status) VALUES (?, ?, ?, ?)",
            (
                str(session.session_id),
                session.created_at.isoformat(),
                json.dumps(session.extracted_data, ensure_ascii=False, allow_nan=False),
                session.status.value,
            ),
        )

    async def get(self, connection: D1Connection, session_id: UUID) -> Session | None:
        row = await connection.fetch_one(
            "SELECT session_id, created_at, extracted_data, status FROM sessions WHERE session_id = ?",
            (str(session_id),),
        )
        return self._from_row(row) if row is not None else None

    async def update(self, connection: D1Connection, session: Session):
        await connection.execute(
            "UPDATE sessions SET extracted_data = ?, status = ? WHERE session_id = ?",
            (
                json.dumps(session.extracted_data, ensure_ascii=False, allow_nan=False),
                session.status.value,
                str(session.session_id),
            ),
        )

    async def delete(self, connection: D1Connection, session_id: UUID):
        await connection.execute(
            "DELETE FROM sessions WHERE session_id = ?", (str(session_id),)
        )

    async def expired(
        self, connection: D1Connection, before: datetime
    ) -> list[Session]:
        """Select finished sessions and sessions created before the UTC cutoff."""
        rows = await connection.fetch_all(
            "SELECT session_id, created_at, extracted_data, status FROM sessions "
            "WHERE status = ? OR created_at < ?",
            (SessionStatus.FINISHED.value, before.isoformat()),
        )
        return [self._from_row(row) for row in rows]
