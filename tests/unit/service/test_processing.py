"""Read extraction from the real test database and mock only Google Sheets access."""

from datetime import UTC, date, datetime
from sqlite3 import Connection
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from form.crud.session import SessionCRUD
from form.exceptions import FatalError, UserInputError
from form.model.form import Form
from form.model.session import Session, SessionStatus
from form.service.processing import ProcessingService
from form.service.session import SessionService
from form.settings import Settings


@pytest.fixture
def processing(
    settings: Settings, session_service: SessionService
) -> ProcessingService:
    return ProcessingService(settings, session_service)


@pytest.fixture
def spreadsheet(mocker: MockerFixture):
    """Provide synthetic activity and family sheets at the external API boundary."""
    spreadsheet = mocker.patch(
        "form.service.processing.GoogleSpreadsheet"
    ).return_value.__enter__.return_value
    activity = mocker.Mock()
    activity.id = 42
    activity.get_all_values.return_value = [
        [
            "Datum",
            "Název akce",
            "Podtitul, téma",
            "Počet účastníků",
            "Počet dětí",
            "Lektor 2/zaměstnanec",
        ],
        ["VZOR", "Synthetic activity"],
        ["", ""],
    ]
    members = mocker.Mock()
    members.id = 43
    members.title = "Seznam unikátních rodin test"
    members.row_count = 10
    members.col_count = 5
    members.get_all_values.return_value = [
        ["", "", "", "", "Aktivity"],
        ["", "", "", "", "Synthetic activity"],
        ["1", "Person Test", "", "", ""],
    ]
    spreadsheet.worksheets.return_value = [members]
    spreadsheet.worksheet.side_effect = {
        "Akce Oříšku": activity,
        members.title: members,
    }.__getitem__
    spreadsheet.fetch_sheet_metadata.return_value = {"sheets": []}
    return spreadsheet


@pytest.mark.anyio
async def test_process_loads_extraction_by_session_id(
    processing: ProcessingService,
    db_conn: Connection,
    form: Form,
    spreadsheet,
):
    """Processing reads the stored form instead of accepting caller-provided data."""
    form.static_fields.date.value = date(2026, 11, 9)
    session = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        status=SessionStatus.REVIEWING,
        extracted_data=form.model_dump(mode="json"),
    )
    SessionCRUD().create(db_conn, session)

    await processing.process(session.session_id)

    spreadsheet.batch_update.assert_called_once()
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    assert {
        "updateCells": {
            "start": {"sheetId": 42, "rowIndex": 2, "columnIndex": 0},
            "rows": [
                {
                    "values": [
                        {
                            "userEnteredValue": {
                                "numberValue": (
                                    date(2026, 11, 9) - date(1899, 12, 30)
                                ).days
                            },
                            "userEnteredFormat": {
                                "numberFormat": {"type": "DATE", "pattern": "d.m.yyyy"}
                            },
                        }
                    ]
                }
            ],
            "fields": "userEnteredValue,userEnteredFormat.numberFormat",
        }
    } in requests


@pytest.mark.anyio
async def test_process_missing_session_rejects_before_google(
    processing: ProcessingService,
    mocker: MockerFixture,
):
    """A missing session cannot trigger a remote write."""
    connection = mocker.patch("form.service.processing.GoogleSpreadsheet")
    with pytest.raises(FatalError, match="Form processing failed"):
        await processing.process(uuid4())
    connection.assert_not_called()


@pytest.fixture
def review_session(db_conn: Connection, form: Form) -> Session:
    session = Session(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        status=SessionStatus.REVIEWING,
        extracted_data=form.model_dump(mode="json"),
    )
    SessionCRUD().create(db_conn, session)
    return session


@pytest.mark.anyio
async def test_processing_failure_cleans_session(
    processing: ProcessingService,
    session_service: SessionService,
    review_session: Session,
    db_conn: Connection,
    spreadsheet,
):
    """A failed remote write is not retried and removes the stored image and session."""
    error = RuntimeError("Synthetic processing failure")
    spreadsheet.batch_update.side_effect = error
    await session_service.save_image(review_session.session_id, b"stored-jpeg")
    with pytest.raises(FatalError, match="Form processing failed") as caught:
        await processing.process(review_session.session_id)
    assert caught.value.__cause__ is error
    spreadsheet.batch_update.assert_called_once()
    assert SessionCRUD().get(db_conn, review_session.session_id) is None
    with pytest.raises(FileNotFoundError):
        await session_service.load_image(review_session.session_id)


@pytest.mark.anyio
async def test_processing_input_error_preserves_reviewable_session(
    processing: ProcessingService,
    session_service: SessionService,
    review_session: Session,
    db_conn: Connection,
    spreadsheet,
):
    """A user error retains extracted data and the image, allowing processing to be retried."""
    await session_service.save_image(review_session.session_id, b"stored-jpeg")
    spreadsheet.batch_update.side_effect = UserInputError("Testovací chyba")
    with pytest.raises(UserInputError, match="Testovací chyba"):
        await processing.process(review_session.session_id)
    assert SessionCRUD().get(db_conn, review_session.session_id) == review_session
    assert await session_service.load_image(review_session.session_id) == b"stored-jpeg"
    spreadsheet.batch_update.side_effect = None
    await processing.process(review_session.session_id)
    stored = SessionCRUD().get(db_conn, review_session.session_id)
    assert stored is not None and stored.status == SessionStatus.FINISHED
    await session_service.delete(review_session.session_id)
