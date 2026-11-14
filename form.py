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
    Correctly split fields of type `Name` to name and surname.

    Every scanned field has attribute `accuracy` describing how much accurate is the parsing result. 100 = absolute certain, 0 = missing value or totally unrecognizeable text
    Missing fields have `value=None, raw_value=None`.
    If the field type is `str`, the `value` and `raw_value` are the same.
    Otherwise `raw_value` contains the scanned text and `value` is the value of the given type.
    If you can't parse the value to the given type, leave `value=None`, and leave `raw_value` and `accuracy` the same as for string fields.

    Returns validated data without storing it.
    """
    return data


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)

