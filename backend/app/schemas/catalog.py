from datetime import datetime, time
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.core.validators import FieldErrors, ImageUrl, PersonName, Price, Rating, ServiceName, ShortText, validate_text
from app.schemas.common import ImageOut, InputModel, ORMModel

ICON_PATTERN = r"^fa-[a-z0-9-]{1,30}$"


# ------------------------------------------------------------------ servicios
class ServiceIn(InputModel):
    name: ServiceName
    description: ShortText = None
    price: Price
    duration_minutes: int = Field(ge=5, le=480)
    icon: str = Field(default="fa-scissors", pattern=ICON_PATTERN)
    is_active: bool = True

    @field_validator("duration_minutes")
    @classmethod
    def multiple_of_5(cls, v: int) -> int:
        if v % 5:
            raise ValueError("La duración debe ser múltiplo de 5 minutos.")
        return v


class ServiceOut(ORMModel):
    id: int
    name: str
    description: str | None
    price: Decimal
    duration_minutes: int
    icon: str
    is_active: bool


class ServiceDetailOut(ServiceOut):
    """Servicio con su ficha (tienda pública, panel y reserva). Los barberos usan ServiceOut (más ligero)."""

    details: str | None = None
    includes: list[str] = []
    offer: str | None = None
    images: list[ImageOut] = []


INCLUDES_MAX = 10


class ServiceContentIn(InputModel):
    """Ficha del servicio: la edita el personal (ADMIN y CAJA). Precio, nombre y duración siguen siendo de ADMIN."""

    details: str | None = Field(default=None, max_length=1000)
    includes: list[str] = Field(default_factory=list, max_length=INCLUDES_MAX)
    offer: str | None = Field(default=None, max_length=120)

    @field_validator("details", "offer")
    @classmethod
    def clean_text(cls, v: str | None, info) -> str | None:
        return validate_text(v, 1000 if info.field_name == "details" else 120)

    @field_validator("includes")
    @classmethod
    def clean_includes(cls, items: list[str]) -> list[str]:
        out: list[str] = []
        for raw in items:
            item = validate_text(raw, 80)
            if not item:
                continue
            if len(item) < 2:
                raise ValueError("Cada elemento debe tener entre 2 y 80 caracteres.")
            if item.lower() not in (x.lower() for x in out):
                out.append(item)
        return out


# ------------------------------------------------------------------ barberos
class BarberIn(InputModel):
    full_name: PersonName
    description: ShortText = None
    photo_url: ImageUrl = None
    rating: Rating
    is_available: bool = True
    is_active: bool = True
    service_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator("service_ids")
    @classmethod
    def unique_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("Selecciona al menos un servicio.")
        return sorted(set(v))


class BarberPublicOut(ORMModel):
    id: int
    full_name: str
    description: str | None
    photo_url: str | None
    rating: Decimal
    is_available: bool
    services: list[ServiceOut]


class BarberOut(BarberPublicOut):
    is_active: bool
    user_id: int | None
    username: str | None = None
    created_at: datetime
    updated_at: datetime


class ScheduleDayIn(InputModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None

    @model_validator(mode="after")
    def check(self):
        if self.end_time <= self.start_time:
            raise FieldErrors({"end_time": "La hora de fin debe ser posterior a la de inicio."})
        if (self.break_start is None) != (self.break_end is None):
            raise FieldErrors({"break_start": "Indica el inicio y el fin del descanso."})
        if self.break_start and self.break_end:
            if not (self.start_time <= self.break_start < self.break_end <= self.end_time):
                raise FieldErrors({"break_start": "El descanso debe estar dentro del horario laboral."})
        return self


class ScheduleIn(InputModel):
    days: list[ScheduleDayIn] = Field(max_length=7)

    @field_validator("days")
    @classmethod
    def unique_days(cls, v: list[ScheduleDayIn]):
        if len({d.weekday for d in v}) != len(v):
            raise ValueError("Cada día de la semana solo puede aparecer una vez.")
        return v


class ScheduleDayOut(ORMModel):
    weekday: int
    start_time: time
    end_time: time
    break_start: time | None
    break_end: time | None


class TimeOffIn(InputModel):
    start_at: datetime
    end_at: datetime
    reason: ShortText = None

    @model_validator(mode="after")
    def check(self):
        if self.end_at <= self.start_at:
            raise FieldErrors({"end_at": "El fin del bloqueo debe ser posterior al inicio."})
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            # Se interpreta en la zona horaria de la barbería en el servicio.
            pass
        return self


class TimeOffOut(ORMModel):
    id: int
    barber_id: int
    start_at: datetime
    end_at: datetime
    reason: str | None
    created_at: datetime
