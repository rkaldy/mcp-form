"""Google Sheets connection setup and cleanup without real credentials or API calls."""

import pytest
from pytest_mock import MockerFixture

from form.utils import GoogleSpreadsheet


@pytest.fixture
def account(mocker: MockerFixture):
    return mocker.patch("form.utils.google_spreadsheet.gspread.service_account")


def test_opens_spreadsheet_and_closes_session(account):
    """Return the library spreadsheet instance and release its connection on exit."""
    url = "https://docs.google.com/spreadsheets/d/synthetic-test"
    client = account.return_value
    with GoogleSpreadsheet(spreadsheet=url) as spreadsheet:
        account.assert_called_once_with(
            filename="gsa.json", scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client.set_timeout.assert_called_once_with(30)
        client.open_by_url.assert_called_once_with(url)
        assert spreadsheet is client.open_by_url.return_value
        client.http_client.session.close.assert_not_called()
    client.http_client.session.close.assert_called_once_with()


@pytest.mark.parametrize("operation", ["set_timeout", "open_by_url"])
def test_entry_failure_closes_session(account, operation: str):
    """Release the session even when opening the context itself fails."""
    client = account.return_value
    getattr(client, operation).side_effect = RuntimeError(
        "Synthetic connection failure"
    )
    with (
        pytest.raises(RuntimeError, match="Synthetic connection failure"),
        GoogleSpreadsheet(spreadsheet="https://docs.google.com/spreadsheets/d/test"),
    ):
        pytest.fail("The context must not be entered")
    client.http_client.session.close.assert_called_once_with()


def test_body_failure_closes_session_and_propagates(account):
    """Cleanup must not suppress errors raised by spreadsheet operations."""
    client = account.return_value
    with (
        pytest.raises(ValueError, match="Synthetic operation failure"),
        GoogleSpreadsheet(spreadsheet="https://docs.google.com/spreadsheets/d/test"),
    ):
        raise ValueError("Synthetic operation failure")
    client.http_client.session.close.assert_called_once_with()
