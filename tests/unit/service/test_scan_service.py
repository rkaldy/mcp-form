from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from freezegun import freeze_time
from pydantic import JsonValue

from form.crud.session import SessionCRUD
from form.database.d1 import D1Connection
from form.exceptions import ScanError, UserInputError
from form.llm.model import FieldType
from form.model.form import Form
from form.model.session import Review, ReviewRequest, Session, SessionStatus
from form.service.scan import ScanService


@pytest.mark.anyio
async def test_scan(
    scan_service: ScanService,
    db_connection: D1Connection,
    image_service,
    llm,
    processing_service,
):
    """Normalize and store the scan, persist extraction and return typed fields for review."""
    response = await scan_service.scan(b"original-jpeg")
    image_service.normalize.assert_called_once_with(b"original-jpeg")
    image_service.save.assert_awaited_once_with(response.session_id, b"normalized-jpeg")
    llm.scan.assert_awaited_once_with(b"normalized-jpeg")
    assert [item.path for item in response.reviews] == [
        "static_fields.member_count",
        "table_fields.0.name",
    ]
    assert response.reviews[0].label == "Počet účastníků"
    assert response.reviews[0].type == FieldType.INTEGER
    assert response.reviews[1].type == FieldType.NAME
    assert response.reviews[1].bounding_box is None
    session = await SessionCRUD().get(db_connection, response.session_id)
    assert session is not None and session.status == SessionStatus.REVIEWING
    processing_service.process.assert_not_awaited()

    image_service.delete.assert_not_awaited()


@pytest.fixture
async def review_session(db_connection: D1Connection, form: Form) -> Session:
    """Prepare an extracted session directly in the database without scanning an image."""
    session = Session(
        session_id=uuid4(),
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        extracted_data=form.model_dump(mode="json"),
        status=SessionStatus.REVIEWING,
    )
    await SessionCRUD().create(db_connection, session)
    return session


@pytest.mark.anyio
async def test_review(
    scan_service: ScanService,
    review_session: Session,
    db_connection: D1Connection,
    image_service,
    processing_service,
):
    """Apply value corrections, process the result and remove the image and session."""
    await scan_service.review(
        ReviewRequest(
            session_id=review_session.session_id,
            reviews=[
                Review(path="static_fields.member_count", value=3),
                Review(
                    path="table_fields.0.name",
                    value={"first_name": "Corrected", "surname": "Person"},
                ),
            ],
        )
    )
    processing_service.process.assert_awaited_once()
    processed = processing_service.process.call_args.args[0]
    assert processed["static_fields"]["member_count"]["value"] == 3
    assert processed["static_fields"]["member_count"]["confidence"] == 74
    assert processed["table_fields"][0]["name"]["value"]["first_name"] == "Corrected"
    image_service.delete.assert_awaited_once_with(review_session.session_id)
    assert await SessionCRUD().get(db_connection, review_session.session_id) is None


@pytest.mark.anyio
async def test_session_lifecycle_at_external_boundaries(
    scan_service: ScanService,
    db_connection: D1Connection,
    image_service,
    llm,
    form: Form,
    processing_service,
):
    """External calls observe the preceding persisted status, including FINISHED before deletion."""

    async def save(image_id: UUID, data: bytes):
        session = await SessionCRUD().get(db_connection, image_id)
        assert session is not None and session.status == SessionStatus.SCANNING
        assert session.extracted_data is None

    image_service.save.side_effect = save
    response = await scan_service.scan(b"jpeg")

    async def process(data: JsonValue):
        session = await SessionCRUD().get(db_connection, response.session_id)
        assert session is not None and session.status == SessionStatus.PROCESSING
        assert session.extracted_data == data

    async def delete(image_id: UUID):
        session = await SessionCRUD().get(db_connection, image_id)
        assert session is not None and session.status == SessionStatus.FINISHED

    processing_service.process.side_effect = process
    image_service.delete.side_effect = delete
    await scan_service.review(
        ReviewRequest(
            session_id=response.session_id,
            reviews=[
                Review(path=item.path, value=item.value) for item in response.reviews
            ],
        )
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode", ["type", "missing", "unknown", "metadata", "negative", "huge"]
)
async def test_invalid_review_preserves_session(
    scan_service: ScanService,
    db_connection: D1Connection,
    image_service,
    processing_service,
    mode: str,
):
    """Reject user mistakes before persisting edits, processing or deleting an image."""
    response = await scan_service.scan(b"jpeg")
    before = await SessionCRUD().get(db_connection, response.session_id)
    reviews = [Review(path=item.path, value=item.value) for item in response.reviews]
    if mode == "type":
        reviews[0].value = "not a number"
    elif mode == "missing":
        reviews.pop()
    else:
        path = {
            "unknown": "unknown",
            "metadata": "static_fields.member_count.confidence",
            "negative": "table_fields.-1.name",
            "huge": f"table_fields.{'9' * 5000}.name",
        }[mode]
        reviews.append(Review(path=path, value=None))
    with pytest.raises(UserInputError):
        await scan_service.review(
            ReviewRequest(session_id=response.session_id, reviews=reviews)
        )
    assert await SessionCRUD().get(db_connection, response.session_id) == before
    processing_service.process.assert_not_awaited()
    image_service.delete.assert_not_awaited()


def test_review_fields_excludes_fields_at_threshold(
    scan_service: ScanService,
    form: Form,
):
    """Fields at the confidence threshold require no review, including table fields."""
    form.static_fields.member_count.confidence = scan_service.confidence_threshold
    form.table_fields[0].name.confidence = scan_service.confidence_threshold

    assert scan_service.review_fields(form) == []


@pytest.mark.anyio
async def test_table_paths_include_row_indexes(scan_service: ScanService, form: Form):
    """Identify an uncertain name in the fifth table row as table_fields.4.name."""
    form.static_fields.member_count.confidence = 100
    row = form.table_fields[0].model_copy(deep=True)
    form.table_fields = [row.model_copy(deep=True) for _ in range(5)]
    for item in form.table_fields[:4]:
        item.name.confidence = 100
    response = await scan_service.scan(b"jpeg")
    assert [item.path for item in response.reviews] == ["table_fields.4.name"]
    assert response.reviews[0].label == "Jméno a příjmení účastníka"


@pytest.mark.anyio
async def test_normalization_failure_creates_no_session(
    scan_service: ScanService, image_service, db_connection: D1Connection, llm
):
    """Do not persist or upload anything if normalization fails at the start of scan."""
    image_service.normalize.side_effect = OSError("synthetic image failure")
    with pytest.raises(ScanError):
        await scan_service.scan(b"invalid")
    image_service.save.assert_not_awaited()
    image_service.delete.assert_not_awaited()
    llm.scan.assert_not_awaited()
    assert await db_connection.fetch_all("SELECT session_id FROM sessions") == []


@pytest.mark.anyio
async def test_llm_failure_removes_image_and_session(
    scan_service: ScanService, image_service, llm, db_connection: D1Connection
):
    """Translate provider failures with their cause after removing both resources."""
    error = RuntimeError("synthetic provider failure")
    llm.scan.side_effect = error
    with pytest.raises(ScanError) as caught:
        await scan_service.scan(b"jpeg")
    assert caught.value.__cause__ is error
    image_id = image_service.save.call_args.args[0]
    image_service.delete.assert_awaited_once_with(image_id)
    assert await SessionCRUD().get(db_connection, image_id) is None


@pytest.mark.anyio
async def test_processing_failure_cleans_session(
    scan_service: ScanService,
    processing_service,
    image_service,
    db_connection: D1Connection,
):
    """A failed processor is not retried and triggers image-then-session cleanup."""
    response = await scan_service.scan(b"jpeg")
    processing_service.process.side_effect = RuntimeError(
        "synthetic processing failure"
    )
    with pytest.raises(ScanError):
        await scan_service.review(
            ReviewRequest(
                session_id=response.session_id,
                reviews=[
                    Review(path=item.path, value=item.value)
                    for item in response.reviews
                ],
            )
        )
    processing_service.process.assert_awaited_once()
    image_service.delete.assert_awaited_once_with(response.session_id)
    assert await SessionCRUD().get(db_connection, response.session_id) is None


@pytest.mark.anyio
@freeze_time("2026-01-02T00:00:00+00:00", real_asyncio=True)
async def test_clean_finished_and_old_sessions(
    scan_service: ScanService,
    db_connection: D1Connection,
    image_service,
    processing_service,
):
    """Clean FINISHED and every status older than 24 hours, while retaining recent reviews."""
    recent = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        status=SessionStatus.REVIEWING,
        extracted_data=None,
    )
    await SessionCRUD().create(db_connection, recent)
    removed = []
    for status in SessionStatus:
        session = Session(
            session_id=uuid4(),
            created_at=datetime.now(UTC) - timedelta(hours=25),
            status=status,
            extracted_data=None,
        )
        await SessionCRUD().create(db_connection, session)
        removed.append(session.session_id)
    finished = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        status=SessionStatus.FINISHED,
        extracted_data=None,
    )
    await SessionCRUD().create(db_connection, finished)
    removed.append(finished.session_id)
    await scan_service.clean()
    assert {call.args[0] for call in image_service.delete.await_args_list} == set(
        removed
    )
    assert await SessionCRUD().get(db_connection, recent.session_id) == recent
    assert len(await db_connection.fetch_all("SELECT session_id FROM sessions")) == 1
    processing_service.process.assert_not_awaited()
