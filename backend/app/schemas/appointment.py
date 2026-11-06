from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.core.validators import ShortText
from app.schemas.common import InputModel, ORMModel

StatusCode = Literal["PENDIENTE", "CONFIRMADA", "ATENDIDA", "CANCELADA"]


class SlotOut(ORMModel):
    time: str
    start_at: datetime
    available: bool
    reason: str | None = None


class AvailabilityOut(ORMModel):
    date: date
    barber_id: int
    service_id: int
    working: bool
    message: str | None = None
    slots: list[SlotOut]


class AppointmentCreateIn(InputModel):
    service_id: int
    barber_id: int
    start_at: datetime
    client_id: int | None = None  # obligatorio cuando reserva el personal
    notes: ShortText = Field(default=None)


class RescheduleIn(InputModel):
    start_at: datetime
    barber_id: int | None = None


class StatusChangeIn(InputModel):
    status: StatusCode
    note: ShortText = None


class CancelIn(InputModel):
    reason: ShortText = None


class PersonRef(ORMModel):
    id: int
    full_name: str


class ClientRef(PersonRef):
    phone: str


class ServiceRef(ORMModel):
    id: int
    name: str
    duration_minutes: int


class HistoryOut(ORMModel):
    from_status: str | None
    to_status: str
    note: str | None
    changed_at: datetime


class AppointmentOut(ORMModel):
    id: int
    client: ClientRef
    barber: PersonRef
    service: ServiceRef
    start_at: datetime
    end_at: datetime
    status: str
    price: Decimal
    notes: str | None
    cancel_reason: str | None
    sale_id: int | None
    google_event_id: str | None = None
    created_at: datetime
    allowed_transitions: list[str] = []
    can_reschedule: bool = False
    can_cancel: bool = False
    can_charge: bool = False


class AppointmentDetailOut(AppointmentOut):
    history: list[HistoryOut] = []
