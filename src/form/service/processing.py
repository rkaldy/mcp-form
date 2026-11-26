"""Copy an activity template into Google Sheets and fill scanned attendance data."""

import asyncio
import json
from collections.abc import Mapping
from datetime import date
from pprint import pprint

# czech-sort is pure Python but does not publish typing metadata.
from czech_sort import bytes_key  # type: ignore[import-untyped]
from gspread import Spreadsheet
from gspread.utils import a1_to_rowcol, absolute_range_name, rowcol_to_a1
from pydantic import JsonValue

from form.exceptions import ProcessingError, UserInputError
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
        header = next((row for row in self.rows if row and row[0]), [])
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

    def find(
        self, start: str, end: str, value: str | None = None
    ) -> tuple[int, int] | None:
        start_row, start_col = a1_to_rowcol(start)
        end_row, end_col = a1_to_rowcol(end)
        for row in range(start_row - 1, end_row):
            for col in range(start_col - 1, end_col):
                cell = (
                    self.rows[row][col]
                    if row < self.row_count and col < len(self.rows[row])
                    else ""
                )
                matches = cell == value if value is not None else bool(cell)
                if matches:
                    return row, col
        return None

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
        self,
        row: int,
        values: Mapping[str, str | int | date | None]
        | Mapping[int, str | int | date | None],
    ) -> list[dict[str, JsonValue]]:
        requests: list[dict[str, JsonValue]] = []
        for column_name, value in values.items():
            column = (
                column_name
                if isinstance(column_name, int)
                else self.column_index[column_name]
            )
            requests.append(
                {
                    "updateCells": {
                        "start": {
                            "sheetId": self.worksheet_id,
                            "rowIndex": row,
                            "columnIndex": column,
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
        await asyncio.to_thread(self.do_process, form)

    @staticmethod
    def find_template(sheet: Sheet, activity_name: str) -> tuple[str, int]:
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
        return name_match, ret

    def do_process(self, form: Form):
        if (
            not form.static_fields.activity_name.value
            or form.static_fields.date.value is None
            or form.static_fields.member_count.value is None
        ):
            raise UserInputError("Název akce, datum a počet účastníků jsou povinné.")

        with GoogleSpreadsheet(spreadsheet=self.target_spreadsheet) as spreadsheet:
            activity_name, requests = self.write_activity(form, spreadsheet)
            requests += self.write_members(form, activity_name, spreadsheet)
            pprint(requests)
            spreadsheet.batch_update({"requests": requests})

    def write_activity(
        self, form: Form, spreadsheet: Spreadsheet
    ) -> tuple[str, list[dict[str, JsonValue]]]:
        requests: list[dict[str, JsonValue]] = []
        sheet = Sheet(spreadsheet, "Akce Oříšku")

        activity_name, template_row = self.find_template(
            sheet, form.static_fields.activity_name.value or ""
        )
        insert_at = next(
            row for row in range(2, sheet.row_count) if not sheet.cell(row, "Datum")
        )
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
                "Datum": form.static_fields.date.value,
                "Podtitul, téma": form.static_fields.activity_theme.value,
                "Počet účastníků": form.static_fields.member_count.value,
                "Počet dětí": sum(
                    bool((row.child_name.value or "").strip())
                    for row in form.table_fields
                ),
                "Lektor 2/zaměstnanec": form.static_fields.lecturer2.value,
            },
        )

        return activity_name, requests

    def write_members(
        self, form: Form, activity_name: str, spreadsheet: Spreadsheet
    ) -> list[dict[str, JsonValue]]:
        worksheet = next(
            (
                sheet
                for sheet in spreadsheet.worksheets()
                if sheet.title.startswith("Seznam unikátních rodin")
            ),
            None,
        )
        if worksheet is None:
            raise ProcessingError("V tabulce chybí záložka Seznam unikátních rodin.")
        sheet = Sheet(spreadsheet, worksheet.title)
        activity_header = sheet.find("D1", "BA3")
        if activity_header is None:
            raise ProcessingError("V seznamu rodin chybí záhlaví aktivit.")
        activity_row, first_activity_col = activity_header
        activity = sheet.find(
            rowcol_to_a1(activity_row + 2, first_activity_col + 1),
            rowcol_to_a1(activity_row + 2, worksheet.col_count),
            activity_name,
        )
        if activity is None:
            raise UserInputError("V seznamu rodin chybí sloupec pro danou akci.")
        activity_col = activity[1]
        member_start = sheet.find("A1", "A10")
        if member_start is None:
            raise ProcessingError("V seznamu rodin nelze najít začátek seznamu členů.")
        first_member_row, name_col = member_start[0], member_start[1] + 1
        city_options = self._city_options(spreadsheet, worksheet.title)
        grid_rows = worksheet.row_count
        requests: list[dict[str, JsonValue]] = []
        for member in form.table_fields:
            person = member.name.value
            if person is None:
                continue
            name = " ".join(
                part.strip()
                for part in (person.surname, person.first_name)
                if part and part.strip()
            )
            if not name:
                continue
            name_key = bytes_key(name)
            member_row = first_member_row
            while member_row < sheet.row_count:
                row = sheet.rows[member_row]
                existing = row[name_col] if name_col < len(row) else ""
                if not existing or existing == name or bytes_key(existing) > name_key:
                    break
                member_row += 1
            existing = (
                sheet.rows[member_row][name_col]
                if member_row < sheet.row_count
                and name_col < len(sheet.rows[member_row])
                else ""
            )
            if existing != name:
                if member_row == grid_rows:
                    requests.append(
                        {
                            "appendDimension": {
                                "sheetId": sheet.id,
                                "dimension": "ROWS",
                                "length": 1,
                            }
                        }
                    )
                else:
                    requests.append(
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet.id,
                                    "dimension": "ROWS",
                                    "startIndex": member_row,
                                    "endIndex": member_row + 1,
                                },
                                "inheritFromBefore": member_row > 0,
                            }
                        }
                    )
                grid_rows += 1
                if member_row > 0:
                    for paste_type in ("PASTE_FORMAT", "PASTE_DATA_VALIDATION"):
                        requests.append(
                            {
                                "copyPaste": {
                                    "source": {
                                        "sheetId": sheet.id,
                                        "startRowIndex": member_row - 1,
                                        "endRowIndex": member_row,
                                    },
                                    "destination": {
                                        "sheetId": sheet.id,
                                        "startRowIndex": member_row,
                                        "endRowIndex": member_row + 1,
                                    },
                                    "pasteType": paste_type,
                                }
                            }
                        )
                inherited_options = city_options.get(member_row - 1, set())
                city_options = {
                    row + (row >= member_row): options
                    for row, options in city_options.items()
                }
                city_options[member_row] = inherited_options
                sheet.rows.insert(member_row, [])
            row = sheet.rows[member_row]
            row.extend([""] * max(0, max(activity_col, 3) + 1 - len(row)))
            attendance = int(row[activity_col]) if row[activity_col] else 0
            city = (member.city.value or "").strip()
            values: dict[int, str | int | None] = {
                1: name,
                2: city if city in city_options.get(member_row, set()) else None,
                3: member.contact.value,
                activity_col: attendance + 1,
            }
            requests.extend(sheet.write_row(member_row, values))
            # Subsequent members must see pending insertions and updated attendance.
            for column, value in values.items():
                row[column] = str(value) if value is not None else ""
        return requests

    @staticmethod
    def _city_options(
        spreadsheet: Spreadsheet, worksheet_name: str
    ) -> dict[int, set[str]]:
        """Read per-row dropdown choices, resolving referenced ranges once."""
        metadata = spreadsheet.fetch_sheet_metadata(
            params={
                "ranges": [absolute_range_name(worksheet_name, "C:C")],
                "includeGridData": True,
                "fields": "sheets(data(startRow,startColumn,rowData(values(dataValidation))))",
            }
        )
        result: dict[int, set[str]] = {}
        ranges: dict[str, set[str]] = {}
        for sheet in metadata.get("sheets", []):
            for grid in sheet.get("data", []):
                column = 2 - grid.get("startColumn", 0)
                for offset, row in enumerate(grid.get("rowData", [])):
                    cells = row.get("values", [])
                    if not 0 <= column < len(cells):
                        continue
                    condition = (
                        cells[column].get("dataValidation", {}).get("condition", {})
                    )
                    values = condition.get("values", [])
                    options: set[str] = set()
                    if condition.get("type") == "ONE_OF_LIST":
                        options = {
                            str(value.get("userEnteredValue", "")).strip()
                            for value in values
                        }
                    elif condition.get("type") == "ONE_OF_RANGE" and values:
                        reference = values[0]["userEnteredValue"].removeprefix("=")
                        if "!" not in reference and ":" in reference:
                            reference = absolute_range_name(worksheet_name, reference)
                        if reference not in ranges:
                            response = spreadsheet.values_get(reference)
                            ranges[reference] = {
                                str(cell).strip()
                                for row_values in response.get("values", [])
                                for cell in row_values
                            }
                        options = ranges[reference]
                    result[grid.get("startRow", 0) + offset] = options
        return result
