import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from anyio import Path

from form.crud.session import SessionCRUD
from form.database.database import Database
from form.exceptions import FatalError
from form.model.session import Session, SessionStatus
from form.settings import Settings

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(self, settings: Settings, database: Database):
        self.database = database
        self.crud = SessionCRUD()
        self.directory = Path(settings.images_path)
        self.session_ttl = settings.session_ttl

    def create(self) -> Session:
        session = Session(
            session_id=uuid4(),
            created_at=datetime.now(UTC),
            extracted_data=None,
            status=SessionStatus.NORMALIZING,
        )
        with self.database.connect() as conn:
            self.crud.create(conn, session)
        return session

    def load(
        self,
        session_id: UUID,
        expected_status: SessionStatus,
        new_status: SessionStatus | None = None,
    ) -> Session:
        with self.database.connect() as conn:
            session = self.crud.get(conn, session_id)
            if session is None:
                raise FatalError(f"Invalid session ID {session_id}")
            if session.status != expected_status:
                raise FatalError(f"Invalid session status {session.status}")
            if new_status:
                session.status = new_status
                self.crud.update(conn, session)
        return session

    def save(self, session: Session, new_status: SessionStatus):
        session.status = new_status
        with self.database.connect() as conn:
            self.crud.update(conn, session)

    async def delete(self, session_id: UUID):
        try:
            await self._image_file(session_id).unlink(missing_ok=True)
            with self.database.connect() as connection:
                self.crud.delete(connection, session_id)
        except Exception:  # noqa: BLE001 -- best-effort cleanup must neither mask the original error nor expose provider payloads.
            logger.error(
                "Session cleanup failed", extra={"session_id": str(session_id)}
            )

    def _image_file(self, session_id: UUID) -> Path:
        return self.directory / f"{session_id}.jpg"

    async def save_image(self, session_id: UUID, image: bytes):
        await self.directory.mkdir(parents=True, exist_ok=True)
        await self._image_file(session_id).write_bytes(image)

    async def load_image(self, session_id: UUID) -> bytes:
        return await self._image_file(session_id).read_bytes()

    async def clean(self):
        try:
            with self.database.connect() as conn:
                sessions = self.crud.expired(conn, datetime.now(UTC) - self.session_ttl)
        except Exception:  # noqa: BLE001 -- cron cleanup failures are logged without returning errors or provider payloads.
            logger.error("Could not select sessions for cleanup")
            return
        for session in sessions:
            await self.delete(session.session_id)
