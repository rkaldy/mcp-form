from contextlib import AbstractContextManager, ExitStack
from types import TracebackType

import gspread


class GoogleSpreadsheet(AbstractContextManager[gspread.Spreadsheet]):
    def __init__(self, spreadsheet: str):
        self.spreadsheet = spreadsheet
        self.stack = ExitStack()

    def __enter__(self) -> gspread.Spreadsheet:
        with ExitStack() as stack:
            client = gspread.service_account(
                filename="gsa.json",
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            # Register cleanup before opening: __exit__ is not called if entry fails.
            stack.callback(client.http_client.session.close)
            client.set_timeout(30)
            spreadsheet = client.open_by_url(self.spreadsheet)
            self.stack = stack.pop_all()
            return spreadsheet

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self.stack.__exit__(exc_type, exc_value, traceback)
