"""Notificaciones, auditoría, configuración e integraciones."""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import RequestMeta, get_current_user, get_request_meta, require_roles
from app.core.errors import BadRequest, NotFound
from app.core.security import sign_state, verify_state
from app.core.timeutils import day_bounds_utc
from app.integrations import calendar
from app.models.audit import AuditLog
from app.models.notification import EmailLog, Notification
from app.models.setting import IntegrationCredential
from app.models.user import ROLE_ADMIN, User
from app.core.validators import Phone
from app.schemas.auth import Email
from app.schemas.common import InputModel, Message, ORMModel, Page
from app.services.audit_service import audit
from app.services.settings_service import get_setting, set_setting

logger = logging.getLogger("mrblack")
router = APIRouter(prefix="/api", tags=["Sistema"])
admin_only = require_roles(ROLE_ADMIN)


# ------------------------------------------------------------------ notificaciones
class NotificationOut(ORMModel):
    id: int
    type: str
    title: str
    message: str
    link: str | None
    is_read: bool
    created_at: datetime


@router.get("/notifications", response_model=list[NotificationOut], tags=["Notificaciones"])
def list_notifications(unread: bool = False, limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.is_read.is_(False))
    return db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)).all()


@router.get("/notifications/unread-count", tags=["Notificaciones"])
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id,
                                                                         Notification.is_read.is_(False)))
    return {"count": n}


@router.post("/notifications/{notification_id}/read", response_model=Message, tags=["Notificaciones"])
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise NotFound("La notificación no existe.")
    n.is_read = True
    db.commit()
    return Message(message="ok")


@router.post("/notifications/read-all", response_model=Message, tags=["Notificaciones"])
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False)).values(is_read=True))
    db.commit()
    return Message(message="Notificaciones marcadas como leídas.")


# ------------------------------------------------------------------ auditoría
class AuditUser(ORMModel):
    id: int
    full_name: str
    username: str


class AuditOut(ORMModel):
    id: int
    user: AuditUser | None
    action: str
    entity: str
    entity_id: str | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


@router.get("/audit", response_model=Page[AuditOut], tags=["Auditoría"])
def list_audit(action: str | None = Query(None, max_length=60), entity: str | None = Query(None, max_length=40),
               user_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db), _: User = Depends(admin_only)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= day_bounds_utc(date_from)[0])
    if date_to:
        stmt = stmt.where(AuditLog.created_at < day_bounds_utc(date_to)[1])
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    return Page(items=rows, total=total, page=page, page_size=page_size)


class EmailLogOut(ORMModel):
    id: int
    to_address: str
    subject: str
    template: str
    status: str
    error: str | None
    created_at: datetime


@router.get("/email-log", response_model=list[EmailLogOut], tags=["Auditoría"])
def email_log(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return db.scalars(select(EmailLog).order_by(EmailLog.created_at.desc()).limit(limit)).all()


# ------------------------------------------------------------------ configuración
class BusinessIn(InputModel):
    name: str = Field(min_length=3, max_length=60)
    legal_name: str = Field(min_length=3, max_length=100)
    ruc: str = Field(pattern=r"^(10|20)\d{9}$")
    address: str = Field(min_length=5, max_length=150)
    phone: Phone
    email: Email


class BookingIn(InputModel):
    slot_interval_minutes: int = Field(ge=5, le=120)
    min_notice_minutes: int = Field(ge=0, le=1440)
    max_days_ahead: int = Field(ge=1, le=365)
    client_cancel_min_hours: int = Field(ge=0, le=168)
    # Opcional: si no se envía se conserva el valor guardado.
    reschedule_min_hours: int | None = Field(default=None, ge=0, le=168)


class SettingsOut(BaseModel):
    business: dict
    booking: dict
    inventory: dict


@router.get("/settings/public", tags=["Configuración"])
def public_settings(db: Session = Depends(get_db)):
    b = get_setting(db, "business")
    return {"business": {k: b[k] for k in ("name", "address", "phone", "email")}, "booking": get_setting(db, "booking")}


@router.get("/settings", response_model=SettingsOut, tags=["Configuración"])
def get_settings_all(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return SettingsOut(business=get_setting(db, "business"), booking=get_setting(db, "booking"),
                       inventory=get_setting(db, "inventory"))


@router.put("/settings/business", tags=["Configuración"])
def put_business(data: BusinessIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                 meta: RequestMeta = Depends(get_request_meta)):
    value = set_setting(db, "business", data.model_dump(), actor.id)
    audit(db, actor.id, "CONFIGURACION_EDITADA", "settings", "business", data.model_dump(), meta)
    db.commit()
    return value


@router.put("/settings/booking", tags=["Configuración"])
def put_booking(data: BookingIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                meta: RequestMeta = Depends(get_request_meta)):
    payload = data.model_dump(exclude_none=True)
    value = set_setting(db, "booking", payload, actor.id)
    audit(db, actor.id, "CONFIGURACION_EDITADA", "settings", "booking", payload, meta)
    db.commit()
    return value


# ------------------------------------------------------------------ Google Calendar
@router.get("/integrations/google/status", tags=["Integraciones"])
def google_status(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    s = get_settings()
    cred = db.get(IntegrationCredential, calendar.PROVIDER)
    return {
        "configured": s.google_enabled,
        "connected": bool(cred) and s.google_enabled,
        "account_email": cred.account_email if cred else None,
        "calendar_id": s.google_calendar_id,
    }


@router.get("/integrations/google/connect", tags=["Integraciones"])
def google_connect(actor: User = Depends(admin_only)):
    if not get_settings().google_enabled:
        raise BadRequest("Configura GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y GOOGLE_REDIRECT_URI en el archivo .env.")
    state = sign_state(f"{actor.id}:{int(datetime.now().timestamp())}")
    return {"authorization_url": calendar.build_authorization_url(state)}


@router.get("/integrations/google/callback", tags=["Integraciones"], include_in_schema=False)
def google_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db), actor: User = Depends(admin_only),
                    meta: RequestMeta = Depends(get_request_meta)):
    front = get_settings().frontend_url
    value = verify_state(state or "")
    if error or not code or not value or value.split(":")[0] != str(actor.id):
        return RedirectResponse(f"{front}/app.html#/configuracion?google=error")
    issued = int(value.split(":")[1])
    if datetime.now().timestamp() - issued > 600:
        return RedirectResponse(f"{front}/app.html#/configuracion?google=error")
    try:
        email = calendar.exchange_code_and_store(db, code)
    except Exception:  # noqa: BLE001
        logger.exception("Falló el intercambio OAuth con Google")
        return RedirectResponse(f"{front}/app.html#/configuracion?google=error")
    audit(db, actor.id, "GOOGLE_CALENDAR_CONECTADO", "integration", calendar.PROVIDER, {"cuenta": email}, meta)
    db.commit()
    return RedirectResponse(f"{front}/app.html#/configuracion?google=ok")


@router.delete("/integrations/google", response_model=Message, tags=["Integraciones"])
def google_disconnect(db: Session = Depends(get_db), actor: User = Depends(admin_only),
                      meta: RequestMeta = Depends(get_request_meta)):
    cred = db.get(IntegrationCredential, calendar.PROVIDER)
    if cred:
        db.delete(cred)
        audit(db, actor.id, "GOOGLE_CALENDAR_DESCONECTADO", "integration", calendar.PROVIDER, None, meta)
        db.commit()
    return Message(message="Google Calendar desconectado.")


@router.get("/health", tags=["Sistema"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
    except SQLAlchemyError:
        # Sin detalles del error: podrían incluir el host de la base de datos.
        logger.warning("Health check: la base de datos no responde")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return {"status": "ok", "database": "connected"}
