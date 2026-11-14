import datetime
from typing import TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")
class ScannedField[T](BaseModel):
   raw_value: str | None = Field(description="Řetězcová hodnota pole")
   value: T | None = Field(description="Parsovaná hodnota pole daného typu")
   accuracy: int = Field(description="Přesnost parsingu: 0 = chybějící nebo zcela nečitelné, 100 = s jistotou čitelné")


class Name(BaseModel):
    name: str | None = Field(description="Část jména a příjemení odpovídající křestnímu jménu")
    surname: str | None = Field(description="Část jména a příjemení odpovídající příjmení")


class Member(BaseModel):
    name: ScannedField[Name] = Field(description="Hodnota ve sloupci s názvem 'Jméno a příjmení účastníka'")
    child_name: ScannedField[str] = Field(description="Hodnota ve sloupci s názvem 'Jméno dítěte nebo dětí'")
    city: ScannedField[str] = Field(description="Hodnota ve sloupci s názvem 'Bydliště jen obec'")
    contact: ScannedField[str] = Field(description="Hodnota ve sloupci s názvem 'Kontakt email nebo tel.'")

class Form(BaseModel):
    activity_name: ScannedField[str] = Field(description="Hodnota pole s názvem 'Název aktivity'")
    activity_theme: ScannedField[str] = Field(description="Hodnota pole s názvem 'Téma'")
    date: ScannedField[datetime.date] = Field(description="Hodnota pole s názvem 'Datum realizace (od - do)'")
    lecturer1: ScannedField[str] = Field(description="Hodnota pole s názvem 'Zaměstnanec MC'")
    lecturer2: ScannedField[str] = Field(description="Hodnota pole s názvem 'Lektor'")
    member_count: ScannedField[int] = Field(description="Hodnota pole s názvem 'Počet účastníků'")
    members: list[Member]

