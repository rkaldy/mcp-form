"""Attendance is derived from table rows rather than an extracted participant count."""

import pytest
from pytest_mock import MockerFixture

from form.model.form import Form
from form.service.processing import ProcessingService
from form.settings import Settings


@pytest.mark.parametrize("participants", [0, 1, 3])
def test_write_activity_counts_table_rows(
    mocker: MockerFixture, settings: Settings, form: Form, participants: int
):
    """Write the number of scanned participant rows into the attendance column."""
    spreadsheet = mocker.Mock()
    spreadsheet.worksheet.return_value.get_all_values.return_value = [
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
    spreadsheet.worksheet.return_value.id = 42
    original = form.table_fields[0]
    form.table_fields = [original.model_copy(deep=True) for _ in range(participants)]

    _, requests = ProcessingService(settings).write_activity(form, spreadsheet)

    assert {
        "updateCells": {
            "start": {"sheetId": 42, "rowIndex": 2, "columnIndex": 3},
            "rows": [{"values": [{"userEnteredValue": {"numberValue": participants}}]}],
            "fields": "userEnteredValue",
        }
    } in requests
