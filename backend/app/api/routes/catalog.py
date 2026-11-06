from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestMeta, barber_of, get_current_user, get_optional_user, get_request_meta, require_roles
from app.core.errors import Forbidden
from app.core.images import read_image_body
from app.models.user import ROLE_ADMIN, ROLE_BARBERO, ROLE_CAJA, User
from app.schemas.appointment import AvailabilityOut, SlotOut
from app.schemas.catalog import (
    BarberIn,
    BarberOut,
    BarberPublicOut,
    ScheduleDayOut,
    ScheduleIn,
    ServiceContentIn,
    ServiceDetailOut,
    ServiceIn,
    TimeOffIn,
    TimeOffOut,
)
from app.schemas.common import ImageOrderIn, Message
from app.services import appointment_service, availability_service, catalog_service

router = APIRouter(prefix="/api", tags=["Servicios y barberos"])
admin_only = require_roles(ROLE_ADMIN)
staff = require_roles(ROLE_ADMIN, ROLE_CAJA)


# ------------------------------------------------------------------ servicios
@router.get("/services", response_model=list[ServiceDetailOut])
def list_services(all: bool = False, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    include_inactive = all and user is not None and user.role_code in (ROLE_ADMIN, ROLE_CAJA)
    return catalog_service.list_services(db, include_inactive)


@router.post("/services", response_model=ServiceDetailOut, status_code=201)
def create_service(data: ServiceIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                   meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.create_service(db, data, actor, meta)


@router.put("/services/{service_id}", response_model=ServiceDetailOut)
def update_service(service_id: int, data: ServiceIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                   meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.update_service(db, service_id, data, actor, meta)


@router.get("/services/{service_id}", response_model=ServiceDetailOut, summary="Ficha del servicio")
def get_service(service_id: int, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    staff_user = user is not None and user.role_code in (ROLE_ADMIN, ROLE_CAJA)
    return catalog_service.get_public_service(db, service_id, include_inactive=staff_user)


@router.patch("/services/{service_id}/content", response_model=ServiceDetailOut,
              summary="Ficha: en qué consiste, qué incluye y oferta (no cambia precio ni duración)")
def update_service_content(service_id: int, data: ServiceContentIn, db: Session = Depends(get_db),
                           actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.update_service_content(db, service_id, data, actor, meta)


# ------------------------------------------------------------------ fotos del servicio (personal: admin y caja)
@router.get("/service-images/{image_id}", response_class=Response, summary="Foto de servicio (pública, cacheable)")
def service_image(image_id: int, db: Session = Depends(get_db)):
    img = catalog_service.get_service_image(db, image_id)
    return Response(img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/services/{service_id}/images", response_model=ServiceDetailOut, status_code=201,
             summary="Subir foto: cuerpo binario image/jpeg, image/png o image/webp (máx. 2 MB)")
async def upload_service_image(service_id: int, request: Request, db: Session = Depends(get_db),
                               actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    data = await read_image_body(request)
    return await run_in_threadpool(catalog_service.add_service_image, db, service_id, data, actor, meta)


@router.delete("/services/{service_id}/images/{image_id}", response_model=ServiceDetailOut)
def delete_service_image(service_id: int, image_id: int, db: Session = Depends(get_db), actor: User = Depends(staff),
                         meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.delete_service_image(db, service_id, image_id, actor, meta)


@router.put("/services/{service_id}/images/order", response_model=ServiceDetailOut)
def order_service_images(service_id: int, data: ImageOrderIn, db: Session = Depends(get_db),
                         actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.reorder_service_images(db, service_id, data.image_ids, actor, meta)


# ------------------------------------------------------------------ barberos
@router.get("/barbers", response_model=list[BarberPublicOut], summary="Barberos activos (vista pública)")
def public_barbers(db: Session = Depends(get_db)):
    # Solo barberos activos con al menos un servicio activo (un perfil recién creado sin servicios no se publica).
    outs = [catalog_service.barber_public_out(b) for b in catalog_service.list_barbers(db, public=True)]
    return [o for o in outs if o.services]


@router.get("/barbers/admin", response_model=list[BarberOut], summary="Todos los barberos (gestión)")
def admin_barbers(db: Session = Depends(get_db), _: User = Depends(staff)):
    return [catalog_service.barber_out(b) for b in catalog_service.list_barbers(db, public=False)]


@router.get("/barbers/{barber_id}", response_model=BarberOut)
def get_barber(barber_id: int, db: Session = Depends(get_db), _: User = Depends(staff)):
    return catalog_service.barber_out(catalog_service.get_barber(db, barber_id))


@router.post("/barbers", response_model=BarberOut, status_code=201)
def create_barber(data: BarberIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                  meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.barber_out(catalog_service.create_barber(db, data, actor, meta))


@router.put("/barbers/{barber_id}", response_model=BarberOut)
def update_barber(barber_id: int, data: BarberIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                  meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.barber_out(catalog_service.update_barber(db, barber_id, data, actor, meta))


def _can_manage_barber_agenda(user: User, barber_id: int, write: bool) -> None:
    if user.role_code == ROLE_ADMIN:
        return
    if user.role_code == ROLE_CAJA and not write:
        return
    if user.role_code == ROLE_BARBERO and barber_of(user).id == barber_id:
        return
    raise Forbidden()


@router.get("/barbers/{barber_id}/schedule", response_model=list[ScheduleDayOut])
def get_schedule(barber_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _can_manage_barber_agenda(user, barber_id, write=False)
    return catalog_service.get_barber(db, barber_id).schedules


@router.put("/barbers/{barber_id}/schedule", response_model=list[ScheduleDayOut])
def set_schedule(barber_id: int, data: ScheduleIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                 meta: RequestMeta = Depends(get_request_meta)):
    return catalog_service.set_schedule(db, barber_id, data, actor, meta)


@router.get("/barbers/{barber_id}/time-off", response_model=list[TimeOffOut])
def list_time_off(barber_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _can_manage_barber_agenda(user, barber_id, write=False)
    return catalog_service.list_time_off(db, barber_id)


@router.post("/barbers/{barber_id}/time-off", response_model=TimeOffOut, status_code=201)
def add_time_off(barber_id: int, data: TimeOffIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                 meta: RequestMeta = Depends(get_request_meta)):
    _can_manage_barber_agenda(user, barber_id, write=True)
    return catalog_service.add_time_off(db, barber_id, data, user, meta)


@router.delete("/barbers/{barber_id}/time-off/{time_off_id}", response_model=Message)
def delete_time_off(barber_id: int, time_off_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                    meta: RequestMeta = Depends(get_request_meta)):
    _can_manage_barber_agenda(user, barber_id, write=True)
    catalog_service.delete_time_off(db, barber_id, time_off_id, user, meta)
    return Message(message="Bloqueo eliminado.")


# ------------------------------------------------------------------ disponibilidad
@router.get("/availability", response_model=AvailabilityOut, tags=["Citas"])
def availability(barber_id: int, service_id: int, date: date, exclude_appointment_id: int | None = None,
                 db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    if exclude_appointment_id:
        # Solo para reprogramar una cita propia (o como personal): no se exponen citas ajenas.
        if user is None:
            raise Forbidden()
        appointment_service.get_for_user(db, exclude_appointment_id, user)
    barber, service = availability_service.resolve_bookable(db, barber_id, service_id)
    day = availability_service.day_availability(db, barber, service, date, exclude_appointment_id)
    return AvailabilityOut(
        date=date, barber_id=barber.id, service_id=service.id, working=day.working, message=day.message,
        slots=[SlotOut(time=s.time, start_at=s.start_at, available=s.available, reason=s.reason) for s in day.slots],
    )
