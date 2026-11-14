from fastmcp import FastMCP

from models import Form

mcp = FastMCP("Form")

@mcp.tool()
def parse_form(data: Form) -> Form:
    """
    Validuj data přečtená z naskenovaného formuláře. Použij pokud uživatel poskytne fotku či sken formuláře.

    Ulož do vstupních polí hodnoty polí podle jejich popisků.
    Při rozpoznávání textu ber v potaz typ a název pole/sloupce, může ti to napomoci s odhadem špatně čitelné hodnoty.
    Pole `members` odpovídá řádkům tabulky.
    """
    return data


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)

