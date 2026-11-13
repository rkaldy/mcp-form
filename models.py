from datetime import date
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class ScanStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    UNREADABLE = "unreadable"

T = TypeVar("T")
class ScannedField(BaseModel, Generic[T]):
   value: T | None
   status: ScanStatus


class Member(BaseModel):
    name: ScannedField[str] = Field(title="Jméno a příjmení účastníka")
    child_name: ScannedField[str] = Field(title="Jméno dítěte nebo dětí")
    city: ScannedField[str] = Field(title="Bydliště jen obec")
    contact: ScannedField[str] = Field(title="Kontakt email nebo tel.")

class Form(BaseModel):
    activity_name: ScannedField[str] = Field(title="Název aktivity")
    activity_theme: ScannedField[str] = Field(title="Téma")
    date: ScannedField[date] = Field(title="Datum realizec (od - do)")
    lecturer1: ScannedField[str] = Field(title="Zaměstnanec MC")
    lecturer2: ScannedField[str] = Field(title="Lektor")
    member_count: ScannedField[int] = Field(title="Počet účastníků")
    members: list[Member]

