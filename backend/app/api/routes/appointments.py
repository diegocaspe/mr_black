from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestMeta, get_current_user, get_request_meta, require_roles
from app.models.user import ROLE_ADMIN, ROLE_CAJA, ROLE_CLIENTE, User
from app.schemas.appointment import (
    AppointmentCreateIn,
    AppointmentDetailOut,
    AppointmentOut,
    CancelIn,
    RescheduleIn,
    StatusChangeIn,
    StatusCode,
)
from app.schemas.common import Page
from app.schemas.sale import ChargeAppointmentIn, SaleOut
from app.services import appointment_service, sale_service
from app.models.appointment import CANCELADA

router = APIRouter(prefix="/api/appointments", tags=["Citas"])
staff = require_roles(ROLE_ADMIN, ROLE_CAJA)


@router.get("", response_model=Page[AppointmentOut])
def list_appointments(
    status: StatusCode | None = None,
    barber_id: int | None = None,
    client_id: int | None = None,
    client: str | None = Query(None, max_length=60, description="Nombre o teléfono del cliente"),
    date_from: date | None = None,
    date_to: date | None = None,
    hide_attended: bool = Query(False, description="Excluye las citas atendidas que ya fueron cobradas"),
    sort: Literal["fecha", "cliente", "barbero", "servicio", "estado", "creada"] = "fecha",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = appointment_service.list_appointments(
        db, user, status=status, barber_id=barber_id, client_id=client_id, client_q=client, date_from=date_from,
        date_to=date_to, hide_attended=hide_attended, sort=sort, order=order, page=page, page_size=page_size,
    )
    return Page(items=[appointment_service.to_out(a, user) for a in items], total=total, page=page, page_size=page_size)


@router.post("", response_model=AppointmentOut, status_code=201)
def create_appointment(data: AppointmentCreateIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(ROLE_CLIENTE, ROLE_ADMIN, ROLE_CAJA)),
                       meta: RequestMeta = Depends(get_request_meta)):
    a = appointment_service.create_appointment(db, data, user, meta, tasks)
    return appointment_service.to_out(a, user)


@router.get("/{appointment_id}", response_model=AppointmentDetailOut)
def get_appointment(appointment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return appointment_service.to_out(appointment_service.get_for_user(db, appointment_id, user), user, detail=True)


@router.patch("/{appointment_id}/status", response_model=AppointmentOut)
def change_status(appointment_id: int, data: StatusChangeIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), meta: RequestMeta = Depends(get_request_meta)):
    a = appointment_service.change_status(db, appointment_id, data.status, data.note, user, meta, tasks)
    return appointment_service.to_out(a, user)


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(appointment_id: int, data: CancelIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
           user: User = Depends(get_current_user), meta: RequestMeta = Depends(get_request_meta)):
    a = appointment_service.change_status(db, appointment_id, CANCELADA, data.reason, user, meta, tasks)
    return appointment_service.to_out(a, user)


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule(appointment_id: int, data: RescheduleIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
               user: User = Depends(get_current_user), meta: RequestMeta = Depends(get_request_meta)):
    a = appointment_service.reschedule(db, appointment_id, data, user, meta, tasks)
    return appointment_service.to_out(a, user)


@router.post("/{appointment_id}/charge", response_model=SaleOut, status_code=201, tags=["Ventas"])
def charge(appointment_id: int, data: ChargeAppointmentIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
           actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    return sale_service.charge_appointment(db, appointment_id, data.payment_method, data.payment, actor, meta, tasks,
                                           items=data.items)
