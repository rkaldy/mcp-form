from enum import Enum
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


class FieldType(Enum):
    STRING = "str"
    INTEGER = "int"
    DECIMAL = "Decimal"
    BOOLEAN = "bool"
    DATE = "date"
    NAME = "Name"


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
