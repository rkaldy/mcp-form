import datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

InputType = TypeVar("InputType", bound=BaseModel)
OutputType = TypeVar("OutputType", bound=BaseModel)
ValueType = TypeVar("ValueType")


class LLMBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )


class Coord(LLMBase):
    x: int
    y: int


class BoundingBox(LLMBase):
    top_left: Coord
    bottom_right: Coord


class Name(LLMBase):
    first_name: str | None
    surname: str | None


class FormField[ValueType](LLMBase):
    bounding_box: BoundingBox | None = Field(
        description="Bounding box of the scanned field in the image coordinates"
    )
    value: ValueType | None = Field(description="Value read from the image")
    confidence: int = Field(
        ge=0,
        le=100,
        description="Scanning confidence, 0=totally unreadable, 100=surely readable",
    )


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
