from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestMeta, get_request_meta, require_roles
from app.models.user import ROLE_ADMIN, ROLE_CAJA, User
from app.schemas.appointment import AppointmentOut
from app.schemas.client import ClientIn, ClientOut, ClientStatsOut
from app.schemas.sale import SaleOut
from app.services import appointment_service, client_service, sale_service

router = APIRouter(prefix="/api/clients", tags=["Clientes"])
staff = require_roles(ROLE_ADMIN, ROLE_CAJA)


@router.get("", response_model=list[ClientStatsOut])
def list_clients(q: str | None = Query(None, max_length=60), db: Session = Depends(get_db), _: User = Depends(staff)):
    return client_service.list_clients(db, q)


@router.post("", response_model=ClientOut, status_code=201)
def create_client(data: ClientIn, db: Session = Depends(get_db), actor: User = Depends(staff),
                  meta: RequestMeta = Depends(get_request_meta)):
    return client_service.to_out(client_service.create_client(db, data, actor, meta))


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db), _: User = Depends(staff)):
    return client_service.to_out(client_service.get_client(db, client_id))


@router.put("/{client_id}", response_model=ClientOut)
def update_client(client_id: int, data: ClientIn, db: Session = Depends(get_db), actor: User = Depends(staff),
                  meta: RequestMeta = Depends(get_request_meta)):
    return client_service.to_out(client_service.update_client(db, client_id, data, actor, meta))


@router.get("/{client_id}/history")
def client_history(client_id: int, db: Session = Depends(get_db), actor: User = Depends(staff)):
    client = client_service.get_client(db, client_id)
    appts, _ = appointment_service.list_appointments(db, actor, client_id=client.id, page_size=200)
    sales, _ = sale_service.list_sales(db, actor, client_id=client.id, page_size=200)
    return {
        "client": client_service.to_out(client),
        "appointments": [AppointmentOut.model_validate(appointment_service.to_out(a, actor)) for a in appts],
        "sales": [SaleOut.model_validate(s) for s in sales],
    }
