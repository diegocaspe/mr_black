from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import RequestMeta
from app.core.errors import NotFound
from app.models.appointment import ATENDIDA, Appointment
from app.models.client import Client
from app.models.sale import SALE_PAGADA, Sale
from app.models.user import User
from app.schemas.client import ClientIn, ClientOut, ClientStatsOut
from app.services.audit_service import audit, diff
from app.services.auth_service import ensure_unique_identity


def to_out(c: Client) -> ClientOut:
    out = ClientOut.model_validate(c)
    out.has_account = c.user_id is not None
    return out


def get_client(db: Session, client_id: int) -> Client:
    c = db.get(Client, client_id)
    if not c:
        raise NotFound("El cliente no existe.")
    return c


def list_clients(db: Session, q: str | None = None) -> list[ClientStatsOut]:
    since = datetime.now(UTC) - timedelta(days=30)
    appt = (
        select(
            Appointment.client_id.label("cid"),
            func.count().label("total"),
            func.count().filter(Appointment.status == ATENDIDA).label("attended"),
            func.count().filter(Appointment.status == ATENDIDA, Appointment.start_at >= since).label("recent"),
            func.max(case((Appointment.status == ATENDIDA, Appointment.start_at))).label("last_visit"),
        )
        .group_by(Appointment.client_id)
        .subquery()
    )
    spent = (
        select(Sale.client_id.label("cid"), func.coalesce(func.sum(Sale.total), 0).label("spent"))
        .where(Sale.status == SALE_PAGADA)
        .group_by(Sale.client_id)
        .subquery()
    )
    stmt = (
        select(Client, appt.c.total, appt.c.attended, appt.c.recent, appt.c.last_visit, spent.c.spent)
        .outerjoin(appt, appt.c.cid == Client.id)
        .outerjoin(spent, spent.c.cid == Client.id)
        .order_by(Client.full_name)
    )
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Client.full_name).like(like), Client.phone.like(like), func.lower(Client.email).like(like)))
    result = []
    for c, total, attended, recent, last_visit, total_spent in db.execute(stmt).all():
        out = ClientStatsOut.model_validate(c)
        out.has_account = c.user_id is not None
        out.total_appointments = total or 0
        out.attended_appointments = attended or 0
        out.visits_last_30_days = recent or 0
        out.last_visit = last_visit
        out.total_spent = f"{Decimal(total_spent or 0):.2f}"
        result.append(out)
    return result


def create_client(db: Session, data: ClientIn, actor: User, meta: RequestMeta) -> Client:
    ensure_unique_identity(db, phone=data.phone)
    c = Client(full_name=data.full_name, phone=data.phone, email=data.email, notes=data.notes)
    db.add(c)
    db.flush()
    audit(db, actor.id, "CLIENTE_CREADO", "client", c.id, data.model_dump(), meta)
    db.commit()
    db.refresh(c)
    return c


def update_client(db: Session, client_id: int, data: ClientIn, actor: User, meta: RequestMeta) -> Client:
    c = get_client(db, client_id)
    ensure_unique_identity(db, phone=data.phone, exclude_client_id=c.id)
    if c.user and data.email and data.email != c.user.email:
        ensure_unique_identity(db, email=data.email, exclude_user_id=c.user.id)
    before = {"full_name": c.full_name, "phone": c.phone, "email": c.email, "notes": c.notes}
    c.full_name, c.phone, c.email, c.notes = data.full_name, data.phone, data.email, data.notes
    if c.user:
        # Mantiene coherente el nombre de la cuenta; el usuario de acceso no cambia.
        c.user.full_name = data.full_name
        if data.email:
            c.user.email = data.email
    audit(db, actor.id, "CLIENTE_EDITADO", "client", c.id, diff(before, data.model_dump()), meta)
    db.commit()
    db.refresh(c)
    return c
