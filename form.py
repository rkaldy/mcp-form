from fastmcp import FastMCP

from models import Form

mcp = FastMCP("Form")

@mcp.tool()
def parse_form(data: Form) -> Form:
    """
    Validate data extracted from a registration form.

    Use when the user provides a photograph or scan
    of a completed registration form.

    Match printed field labels to the `Form` schema field titles.
    The `members` field corresponds to the table rows. Match table column headers to the `Member` schema field titles.

    Correctly scanned fields have status `OK`.
    Missing fields have value `None` and status `MISSING`. Never infer or invent missing values.
    Unreadable fields value `None` and status `UNREADABLE`.
    Take into account the field types. If you can't validate the scanned value as the given type, the value should be `None` and status `UNREADABLE`.

    Returns validated data without storing it.
    """
    return data


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)

