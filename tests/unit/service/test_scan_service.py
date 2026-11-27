import json
from datetime import UTC, date, datetime
from sqlite3 import Connection
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from form.crud.session import SessionCRUD
from form.exceptions import FatalError, UserInputError
from form.llm.instruction import Instruction
from form.llm.model import BoundingBox, Coord, FieldType, FormTransformation
from form.model.form import Form
from form.model.session import Review, ReviewRequest, Session, SessionStatus
from form.service.scan import ScanService
from form.service.session import SessionService
from form.settings import Settings


@pytest.fixture
def scan_service(
    session_service: SessionService, image_service, llm, settings: Settings
) -> ScanService:
    return ScanService(settings, session_service, image_service, llm)


@pytest.fixture
def session(db_conn: Connection) -> Session:
    """Persist a normalized session ready for the scanning phase."""
    session = Session(
        session_id=uuid4(),
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        extracted_data=None,
        status=SessionStatus.NORMALIZING,
    )
    SessionCRUD().create(db_conn, session)
    return session


@pytest.mark.anyio
async def test_normalize(
    scan_service: ScanService,
    db_conn: Connection,
    image_service,
    llm,
):
    """Persist a normalizing session, locate the form and save its transformed image."""
    transformation = FormTransformation(
        rotate=90,
        crop=BoundingBox(top_left=Coord(x=10, y=20), bottom_right=Coord(x=110, y=220)),
    )
    llm.scan.return_value = transformation

    await scan_service.normalize(b"original-jpeg")

    rows = db_conn.execute("SELECT session_id FROM sessions").fetchall()
    assert len(rows) == 1
    session_id = UUID(rows[0][0])
    session = SessionCRUD().get(db_conn, session_id)
    assert session is not None
    assert session.status == SessionStatus.NORMALIZING
    assert session.extracted_data is None
    image_service.normalize.assert_called_once_with(b"original-jpeg")
    llm.scan.assert_awaited_once_with(
        Instruction.ROTATE_CROP, b"normalized-jpeg", FormTransformation
    )
    image_service.rotate_crop.assert_called_once_with(
        b"normalized-jpeg", transformation.rotate, transformation.crop
    )
    assert await scan_service.sessions.load_image(session_id) == b"cropped-jpeg"


@pytest.mark.anyio
async def test_scan(
    scan_service: ScanService,
    session: Session,
    db_conn: Connection,
    image_service,
    llm,
):
    """Scan the form, persist extraction and return typed fields for review."""
    await scan_service.sessions.save_image(session.session_id, b"stored-jpeg")
    reviews = await scan_service.scan(session.session_id)

    llm.scan.assert_awaited_once_with(Instruction.SCAN, b"stored-jpeg", Form)
    image_service.normalize.assert_not_called()
    assert [item.path for item in reviews] == [
        "static_fields.date",
        "table_fields.0.name",
    ]
    assert reviews[0].label == "Datum realizace (od - do)"
    assert reviews[0].type == FieldType.DATE
    assert reviews[1].type == FieldType.NAME
    assert reviews[1].bounding_box is None
    stored = SessionCRUD().get(db_conn, session.session_id)
    assert stored is not None and stored.status == SessionStatus.REVIEWING


@pytest.fixture
def review_session(db_conn: Connection, form: Form, session: Session) -> Session:
    """Prepare an extracted session directly in the database without scanning an image."""
    session.extracted_data = form.model_dump(mode="json")
    session.status = SessionStatus.REVIEWING
    SessionCRUD().update(db_conn, session)
    return session


@pytest.mark.anyio
async def test_review(
    scan_service: ScanService,
    review_session: Session,
    db_conn: Connection,
    image_service,
):
    """Apply and persist value corrections while retaining the session for processing."""
    await scan_service.review(
        ReviewRequest(
            session_id=review_session.session_id,
            reviews=[
                Review(path="static_fields.date", value="2026-01-03"),
                Review(
                    path="table_fields.0.name",
                    value={"first_name": "Corrected", "surname": "Person"},
                ),
            ],
        )
    )
    stored = SessionCRUD().get(db_conn, review_session.session_id)
    assert stored is not None and stored.status == SessionStatus.REVIEWING
    processed = Form.model_validate_json(json.dumps(stored.extracted_data))
    assert processed.static_fields.date.value == date(2026, 1, 3)
    assert processed.static_fields.date.confidence == 74
    assert processed.table_fields[0].name.value is not None
    assert processed.table_fields[0].name.value.first_name == "Corrected"


@pytest.mark.anyio
async def test_invalid_review_preserves_session(
    scan_service: ScanService,
    review_session: Session,
    form: Form,
    db_conn: Connection,
    image_service,
):
    """Translate an invalid value to UserInputError while retaining the original session."""
    reviews = [
        Review(path=item.path, value=item.value)
        for item in scan_service._review_fields(form)
    ]
    reviews[0].value = "not a date"
    with pytest.raises(UserInputError, match="Chybně zadaná hodnota") as caught:
        await scan_service.review(
            ReviewRequest(session_id=review_session.session_id, reviews=reviews)
        )
    assert isinstance(caught.value.__cause__, ValidationError)
    assert SessionCRUD().get(db_conn, review_session.session_id) == review_session


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["missing", "unknown", "metadata", "negative", "huge"])
async def test_invalid_review_paths_remove_session(
    scan_service: ScanService,
    review_session: Session,
    form: Form,
    db_conn: Connection,
    image_service,
    mode: str,
):
    """Invalid or incomplete paths are FatalError failures that clean up the session."""
    reviews = [
        Review(path=item.path, value=item.value)
        for item in scan_service._review_fields(form)
    ]
    if mode == "missing":
        reviews.pop()
    else:
        path = {
            "unknown": "unknown",
            "metadata": "static_fields.date.confidence",
            "negative": "table_fields.-1.name",
            "huge": f"table_fields.{'9' * 5000}.name",
        }[mode]
        reviews.append(Review(path=path, value=None))
    with pytest.raises(FatalError, match="Form review failed") as caught:
        await scan_service.review(
            ReviewRequest(session_id=review_session.session_id, reviews=reviews)
        )
    assert isinstance(caught.value.__cause__, FatalError)
    assert SessionCRUD().get(db_conn, review_session.session_id) is None


def test_review_fields_excludes_fields_at_threshold(
    scan_service: ScanService,
    form: Form,
):
    """Fields at the confidence threshold require no review, including table fields."""
    form.static_fields.date.confidence = scan_service.confidence_threshold
    form.table_fields[0].name.confidence = scan_service.confidence_threshold

    assert scan_service._review_fields(form) == []


@pytest.mark.anyio
async def test_table_paths_include_row_indexes(
    scan_service: ScanService, session: Session, form: Form
):
    """Identify an uncertain name in the fifth table row as table_fields.4.name."""
    form.static_fields.date.confidence = 100
    row = form.table_fields[0].model_copy(deep=True)
    form.table_fields = [row.model_copy(deep=True) for _ in range(5)]
    for item in form.table_fields[:4]:
        item.name.confidence = 100
    await scan_service.sessions.save_image(session.session_id, b"stored-jpeg")
    reviews = await scan_service.scan(session.session_id)
    assert [item.path for item in reviews] == ["table_fields.4.name"]
    assert reviews[0].label == "Jméno a příjmení účastníka"


@pytest.mark.anyio
async def test_normalization_failure_removes_session(
    scan_service: ScanService, image_service, db_conn: Connection, llm
):
    """Clean up the newly created session if EXIF normalization fails."""
    image_service.normalize.side_effect = OSError("synthetic image failure")
    with pytest.raises(FatalError):
        await scan_service.normalize(b"invalid JPEG")
    llm.scan.assert_not_awaited()
    assert db_conn.execute("SELECT session_id FROM sessions").fetchall() == []


@pytest.mark.anyio
async def test_llm_failure_removes_image_and_session(
    scan_service: ScanService, session: Session, image_service, llm, db_conn: Connection
):
    """Translate provider failures with their cause after removing both resources."""
    error = RuntimeError("synthetic provider failure")
    llm.scan.side_effect = error
    await scan_service.sessions.save_image(session.session_id, b"stored-jpeg")
    with pytest.raises(FatalError) as caught:
        await scan_service.scan(session.session_id)
    assert caught.value.__cause__ is error
    with pytest.raises(FileNotFoundError):
        await scan_service.sessions.load_image(session.session_id)
    assert SessionCRUD().get(db_conn, session.session_id) is None
