import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PrioritateEnum(str, Enum):
    scazuta = "scazuta"
    medie = "medie"
    ridicata = "ridicata"


class UtilizatorInregistrare(BaseModel):
    nume: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=200)
    parola: str = Field(..., min_length=6, max_length=200)

    @field_validator("email")
    @classmethod
    def valideaza_email(cls, v: str) -> str:
        pattern = r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Adresa de email nu este validă")
        return v.lower()


class UtilizatorAutentificare(BaseModel):
    email: str
    parola: str


class SarcinaCreare(BaseModel):
    titlu: str = Field(..., min_length=1, max_length=200)
    descriere: str = Field("", max_length=2000)
    prioritate: PrioritateEnum = PrioritateEnum.medie
    data_limita: Optional[str] = Field(
        None,
        description="Data limită în format ISO 8601 (ex: 2026-12-31)",
    )
    categorie: Optional[str] = Field(None, max_length=50)

    @field_validator("data_limita")
    @classmethod
    def valideaza_data_limita(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Accept full ISO datetime strings or plain date strings (YYYY-MM-DD).
        date_pattern = r"^\d{4}-\d{2}-\d{2}(T[\d:.+Z-]*)?$"
        if not re.match(date_pattern, v):
            raise ValueError(
                "data_limita trebuie să fie în format ISO 8601 (ex: 2026-12-31)"
            )
        return v


class SarcinaActualizare(BaseModel):
    titlu: Optional[str] = Field(None, min_length=1, max_length=200)
    descriere: Optional[str] = Field(None, max_length=2000)
    finalizata: Optional[bool] = None
    prioritate: Optional[PrioritateEnum] = None
    data_limita: Optional[str] = Field(None)
    categorie: Optional[str] = Field(None, max_length=50)

    @field_validator("data_limita")
    @classmethod
    def valideaza_data_limita(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        date_pattern = r"^\d{4}-\d{2}-\d{2}(T[\d:.+Z-]*)?$"
        if not re.match(date_pattern, v):
            raise ValueError(
                "data_limita trebuie să fie în format ISO 8601 (ex: 2026-12-31)"
            )
        return v