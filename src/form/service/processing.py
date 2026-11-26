"""Copy an activity template into Google Sheets and fill scanned attendance data."""

import asyncio
import json
from datetime import date
from pprint import pprint

from gspread import Spreadsheet
from pydantic import JsonValue

from form.exceptions import ProcessingError
from form.model.form import Form
from form.settings import Settings
from form.utils import GoogleSpreadsheet


class Sheet:
    def __init__(self, spreadsheet: Spreadsheet, worksheet_name: str):
        self.worksheet_name = worksheet_name
        worksheet = spreadsheet.worksheet(worksheet_name)
        self.worksheet_id = worksheet.id
        self.rows: list[list[str]] = [
            [str(cell).strip() for cell in row] for row in worksheet.get_all_values()
        ]
        self.column_index: dict[str, int] = {}
        header = next(row for row in self.rows if row[0])
        for index, cell in enumerate(header):
            if cell:
                self.column_index[cell] = index

    @property
    def id(self) -> int:
        return self.worksheet_id

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def cell(self, row: int, col_name: str) -> str:
        if not col_name in self.column_index:
            raise ProcessingError(
                f"V tabulce {self.worksheet_name} chybí sloupec '{col_name}'"
            )
        col = self.column_index[col_name]
        return self.rows[row][col] if len(self.rows[row]) > col else ""

    def _cell_value(self, value: str | int | date | None) -> dict[str, JsonValue]:
        if type(value) is str:
            return {"userEnteredValue": {"stringValue": value}}
        elif type(value) is int:
            return {"userEnteredValue": {"numberValue": value}}
        elif type(value) is date:
            return {
                "userEnteredValue": {
                    "numberValue": (value - date(1899, 12, 30)).days,
                },
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "DATE",
                        "pattern": "d.m.yyyy",
                    },
                },
            }
        else:
            return {}

    def write_row(
        self, row: int, values: dict[str, str | int | date | None]
    ) -> list[dict[str, JsonValue]]:
        requests: list[dict[str, JsonValue]] = []
        for column_name, value in values.items():
            requests.append(
                {
                    "updateCells": {
                        "start": {
                            "sheetId": self.worksheet_id,
                            "rowIndex": row,
                            "columnIndex": self.column_index[column_name],
                        },
                        "rows": [{"values": [self._cell_value(value)]}],
                        "fields": "userEnteredValue,userEnteredFormat.numberFormat"
                        if type(value) is date
                        else "userEnteredValue",
                    }
                }
            )
        return requests


class ProcessingService:
    def __init__(self, settings: Settings):
        self.target_spreadsheet = settings.target_spreadsheet

    async def process(self, data: JsonValue):
        """Write one completed activity; do not retry potentially successful writes."""
        form = Form.model_validate_json(json.dumps(data))
        await asyncio.to_thread(self.write_activity, form)

    @staticmethod
    def find_template(sheet: Sheet, activity_name: str) -> int:
        name_match = ""
        ret: int | None = None
        for row in range(sheet.row_count):
            if sheet.cell(row, "Datum") == "VZOR":
                template_name = sheet.cell(row, "Název akce")
                if activity_name.startswith(template_name) and len(template_name) > len(
                    name_match
                ):
                    name_match = template_name
                    ret = row
        if ret is None:
            raise ProcessingError(
                f"V tabulce musí být právě jeden řádek 'VZOR' pro akci '{activity_name}'."
            )
        return ret

    def write_activity(self, form: Form):
        activity_name = form.static_fields.activity_name.value
        activity_date = form.static_fields.date.value
        member_count = form.static_fields.member_count.value
        if not activity_name or activity_date is None or member_count is None:
            raise ProcessingError("Název akce, datum a počet účastníků jsou povinné.")

        with GoogleSpreadsheet(spreadsheet=self.target_spreadsheet) as spreadsheet:
            sheet = Sheet(spreadsheet, "Akce Oříšku")
            template_row = self.find_template(sheet, activity_name)
            insert_at = next(
                row for row in range(2, sheet.row_count) if not sheet.cell(row, "Datum")
            )
            requests: list[dict[str, JsonValue]] = []
            requests.append(
                {
                    "insertDimension": {
                        "range": {
                            "sheetId": sheet.id,
                            "dimension": "ROWS",
                            "startIndex": insert_at,
                            "endIndex": insert_at + 1,
                        },
                        "inheritFromBefore": False,
                    }
                }
            )
            requests.append(
                {
                    "copyPaste": {
                        "source": {
                            "sheetId": sheet.id,
                            "startRowIndex": template_row + 1,
                            "endRowIndex": template_row + 2,
                        },
                        "destination": {
                            "sheetId": sheet.id,
                            "startRowIndex": insert_at,
                            "endRowIndex": insert_at + 1,
                        },
                        "pasteType": "PASTE_NORMAL",
                    }
                }
            )
            requests += sheet.write_row(
                insert_at,
                {
                    "Datum": activity_date,
                    "Podtitul, téma": form.static_fields.activity_theme.value,
                    "Počet účastníků": member_count,
                    "Počet dětí": sum(
                        bool((row.child_name.value or "").strip())
                        for row in form.table_fields
                    ),
                    "Lektor 2/zaměstnanec": form.static_fields.lecturer2.value,
                },
            )
            # Google validates the whole batch before applying any of its writes.
            pprint(requests)
            spreadsheet.batch_update({"requests": requests})
