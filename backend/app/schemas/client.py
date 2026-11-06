from datetime import datetime

from app.core.validators import PersonName, Phone, ShortText
from app.schemas.auth import Email
from app.schemas.common import InputModel, ORMModel


class ClientIn(InputModel):
    full_name: PersonName
    phone: Phone
    email: Email | None = None
    notes: ShortText = None


class ClientOut(ORMModel):
    id: int
    full_name: str
    phone: str
    email: str | None
    notes: str | None
    is_active: bool
    has_account: bool = False
    created_at: datetime


class ClientStatsOut(ClientOut):
    total_appointments: int = 0
    attended_appointments: int = 0
    visits_last_30_days: int = 0
    total_spent: str = "0.00"
    last_visit: datetime | None = None
