import datetime

from pydantic import Field

from form.llm.model import FormField, LLMBase, Name


class TableFields(LLMBase):
    name: FormField[Name] = Field(
        description="Column value with label 'Jméno a příjmení účastníka'"
    )
    child_name: FormField[str] = Field(
        description="Column value with label 'Jméno dítěte nebo dětí'"
    )
    city: FormField[str] = Field(
        description="Column value with label 'Bydliště jen obec'"
    )
    contact: FormField[str] = Field(
        description="Column value with label 'Kontakt email nebo tel.'"
    )


class StaticFields(LLMBase):
    activity_name: FormField[str] = Field(
        description="Field value with label 'Název aktivity'"
    )
    activity_theme: FormField[str] = Field(description="Field value with label 'Téma'")
    date: FormField[datetime.date] = Field(
        description="Field value with label 'Datum realizace (od - do)'"
    )
    lecturer1: FormField[str] = Field(
        description="Field value with label 'Zaměstnanec MC'"
    )
    lecturer2: FormField[str] = Field(description="Field value with label 'Lektor'")
    member_count: FormField[int] = Field(
        description="Field value with label 'Počet účastníků'"
    )


class Form(LLMBase):
    static_fields: StaticFields = Field(description="Fields in form header and footer")
    table_fields: list[TableFields] = Field(description="Fields in the form table")
