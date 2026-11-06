"""Servicios de la barbería y barberos (perfil, servicios, horarios y bloqueos)."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestMeta
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.timeutils import to_aware
from app.models.appointment import ACTIVE_STATUSES, Appointment
from app.models.barber import Barber, BarberSchedule, BarberTimeOff
from app.models.service import Service, ServiceImage
from app.models.user import User
from app.schemas.catalog import (
    BarberIn,
    BarberOut,
    BarberPublicOut,
    ScheduleIn,
    ServiceContentIn,
    ServiceIn,
    ServiceOut,
    TimeOffIn,
)
from app.services import image_service
from app.services.audit_service import audit, diff

# ------------------------------------------------------------------ servicios


def list_services(db: Session, include_inactive: bool = False) -> list[Service]:
    stmt = select(Service).order_by(Service.id)
    if not include_inactive:
        stmt = stmt.where(Service.is_active.is_(True))
    return list(db.scalars(stmt).all())


def get_service(db: Session, service_id: int) -> Service:
    s = db.get(Service, service_id)
    if not s:
        raise NotFound("El servicio no existe.")
    return s


def _service_name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Service.id).where(func.lower(Service.name) == name.lower())
    if exclude_id:
        stmt = stmt.where(Service.id != exclude_id)
    return db.scalar(stmt) is not None


def create_service(db: Session, data: ServiceIn, actor: User, meta: RequestMeta) -> Service:
    if _service_name_taken(db, data.name):
        raise Conflict("Ya existe un servicio con ese nombre.", fields={"name": "Nombre duplicado."})
    s = Service(**data.model_dump())
    db.add(s)
    db.flush()
    audit(db, actor.id, "SERVICIO_CREADO", "service", s.id, data.model_dump(), meta)
    db.commit()
    db.refresh(s)
    return s


def update_service(db: Session, service_id: int, data: ServiceIn, actor: User, meta: RequestMeta) -> Service:
    s = get_service(db, service_id)
    if _service_name_taken(db, data.name, exclude_id=s.id):
        raise Conflict("Ya existe un servicio con ese nombre.", fields={"name": "Nombre duplicado."})
    before = {k: getattr(s, k) for k in data.model_dump()}
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    changes = diff(before, data.model_dump())
    action = "SERVICIO_EDITADO"
    if "is_active" in changes:
        action = "SERVICIO_ACTIVADO" if data.is_active else "SERVICIO_DESACTIVADO"
    audit(db, actor.id, action, "service", s.id, changes, meta)
    db.commit()
    db.refresh(s)
    return s


# ------------------------------------------------------------------ ficha del servicio (personal: admin y caja)
GALLERY = image_service.Gallery(model=ServiceImage, owner_fk="service_id", entity="service", action_prefix="SERVICIO")


def get_public_service(db: Session, service_id: int, include_inactive: bool = False) -> Service:
    s = get_service(db, service_id)
    if not s.is_active and not include_inactive:
        raise NotFound("El servicio no existe o no está disponible.")
    return s


def update_service_content(db: Session, service_id: int, data: ServiceContentIn, actor: User, meta: RequestMeta) -> Service:
    """Actualiza solo la ficha (en qué consiste, qué incluye y oferta); no toca precio, nombre ni duración."""
    s = get_service(db, service_id)
    before = {"details": s.details, "includes": list(s.includes or []), "offer": s.offer}
    after = data.model_dump()
    for k, v in after.items():
        setattr(s, k, v)
    changes = diff(before, after)
    if changes:
        audit(db, actor.id, "SERVICIO_FICHA_EDITADA", "service", s.id, changes, meta)
    db.commit()
    return image_service.refreshed(db, s)


def add_service_image(db: Session, service_id: int, data: bytes, actor: User, meta: RequestMeta) -> Service:
    return image_service.add_image(db, GALLERY, get_service(db, service_id), data, actor, meta)


def delete_service_image(db: Session, service_id: int, image_id: int, actor: User, meta: RequestMeta) -> Service:
    return image_service.delete_image(db, GALLERY, get_service(db, service_id), image_id, actor, meta)


def reorder_service_images(db: Session, service_id: int, image_ids: list[int], actor: User, meta: RequestMeta) -> Service:
    return image_service.reorder_images(db, GALLERY, get_service(db, service_id), image_ids, actor, meta)


def get_service_image(db: Session, image_id: int) -> ServiceImage:
    return image_service.get_image(db, ServiceImage, image_id)


# ------------------------------------------------------------------ barberos


def barber_out(b: Barber) -> BarberOut:
    out = BarberOut.model_validate(b)
    out.username = b.user.username if b.user else None
    return out


def barber_public_out(b: Barber) -> BarberPublicOut:
    """Vista pública: solo servicios activos y sin datos internos."""
    return BarberPublicOut(
        id=b.id,
        full_name=b.full_name,
        description=b.description,
        photo_url=b.photo_url,
        rating=b.rating,
        is_available=b.is_available,
        services=[ServiceOut.model_validate(s) for s in b.services if s.is_active],
    )


def list_barbers(db: Session, public: bool) -> list[Barber]:
    stmt = select(Barber).order_by(Barber.id)
    if public:
        stmt = stmt.where(Barber.is_active.is_(True))
    return list(db.scalars(stmt).all())


def get_barber(db: Session, barber_id: int) -> Barber:
    b = db.get(Barber, barber_id)
    if not b:
        raise NotFound("El barbero no existe.")
    return b


def _resolve_services(db: Session, ids: list[int]) -> list[Service]:
    services = list(db.scalars(select(Service).where(Service.id.in_(ids))).all())
    if len(services) != len(set(ids)):
        raise BadRequest("Uno de los servicios seleccionados no existe.", fields={"service_ids": "Servicio inválido."})
    return services


def _future_active_count(db: Session, barber_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.barber_id == barber_id,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.start_at > datetime.now(UTC),
        )
    )


def _snapshot(b: Barber) -> dict:
    return {
        "full_name": b.full_name,
        "description": b.description,
        "photo_url": b.photo_url,
        "rating": str(b.rating),
        "is_available": b.is_available,
        "is_active": b.is_active,
        "service_ids": sorted(s.id for s in b.services),
    }


def create_barber(db: Session, data: BarberIn, actor: User, meta: RequestMeta) -> Barber:
    b = Barber(
        full_name=data.full_name,
        description=data.description,
        photo_url=data.photo_url,
        rating=data.rating,
        is_available=data.is_available,
        is_active=data.is_active,
    )
    b.services = _resolve_services(db, data.service_ids)
    db.add(b)
    db.flush()
    audit(db, actor.id, "BARBERO_CREADO", "barber", b.id, _snapshot(b), meta)
    db.commit()
    db.refresh(b)
    return b


def update_barber(db: Session, barber_id: int, data: BarberIn, actor: User, meta: RequestMeta) -> Barber:
    """0024802 / 0024794: la edición se persiste en una transacción y se devuelve el registro releído."""
    b = get_barber(db, barber_id)
    before = _snapshot(b)
    if b.is_active and not data.is_active:
        pending = _future_active_count(db, b.id)
        if pending:
            raise Conflict(
                f"El barbero tiene {pending} cita(s) futura(s) activa(s). Reprográmalas o cancélalas antes de darlo de baja.",
                code="barber_has_appointments",
            )
    b.full_name = data.full_name
    b.description = data.description
    b.photo_url = data.photo_url
    b.rating = data.rating
    b.is_available = data.is_available
    b.is_active = data.is_active
    b.services = _resolve_services(db, data.service_ids)
    if b.user and b.user.full_name != data.full_name:
        b.user.full_name = data.full_name
    db.flush()
    changes = diff(before, _snapshot(b))
    if changes:
        action = "BARBERO_EDITADO"
        if "is_active" in changes:
            action = "BARBERO_ACTIVADO" if data.is_active else "BARBERO_DESACTIVADO"
        audit(db, actor.id, action, "barber", b.id, changes, meta)
    db.commit()
    db.expire_all()
    return get_barber(db, barber_id)


def set_schedule(db: Session, barber_id: int, data: ScheduleIn, actor: User, meta: RequestMeta) -> list[BarberSchedule]:
    b = get_barber(db, barber_id)
    b.schedules.clear()
    db.flush()
    for d in sorted(data.days, key=lambda x: x.weekday):
        b.schedules.append(BarberSchedule(**d.model_dump()))
    audit(db, actor.id, "HORARIO_ACTUALIZADO", "barber", b.id,
          {"dias": [f"{d.weekday}:{d.start_time}-{d.end_time}" for d in data.days]}, meta)
    db.commit()
    db.refresh(b)
    return b.schedules


def list_time_off(db: Session, barber_id: int, upcoming_only: bool = True) -> list[BarberTimeOff]:
    stmt = select(BarberTimeOff).where(BarberTimeOff.barber_id == barber_id).order_by(BarberTimeOff.start_at)
    if upcoming_only:
        stmt = stmt.where(BarberTimeOff.end_at > datetime.now(UTC))
    return list(db.scalars(stmt).all())


def add_time_off(db: Session, barber_id: int, data: TimeOffIn, actor: User, meta: RequestMeta) -> BarberTimeOff:
    get_barber(db, barber_id)
    start, end = to_aware(data.start_at), to_aware(data.end_at)
    if end <= datetime.now(UTC):
        raise BadRequest("El bloqueo debe terminar en el futuro.", fields={"end_at": "Fecha pasada."})
    conflicts = db.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.barber_id == barber_id,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.start_at < end,
            Appointment.end_at > start,
        )
    )
    if conflicts:
        raise Conflict(
            f"Hay {conflicts} cita(s) activa(s) en ese rango. Reprográmalas o cancélalas antes de bloquear el horario.",
            code="time_off_conflict",
        )
    t = BarberTimeOff(barber_id=barber_id, start_at=start, end_at=end, reason=data.reason, created_by=actor.id)
    db.add(t)
    db.flush()
    audit(db, actor.id, "BLOQUEO_CREADO", "barber", barber_id,
          {"inicio": start.isoformat(), "fin": end.isoformat(), "motivo": data.reason}, meta)
    db.commit()
    db.refresh(t)
    return t


def delete_time_off(db: Session, barber_id: int, time_off_id: int, actor: User, meta: RequestMeta) -> None:
    t = db.get(BarberTimeOff, time_off_id)
    if not t or t.barber_id != barber_id:
        raise NotFound("El bloqueo no existe.")
    audit(db, actor.id, "BLOQUEO_ELIMINADO", "barber", barber_id,
          {"inicio": t.start_at.isoformat(), "fin": t.end_at.isoformat()}, meta)
    db.delete(t)
    db.commit()
