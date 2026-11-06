import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.deps import RequestMeta, active_user_ids_with_roles
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.timeutils import day_bounds_utc, tz
from app.integrations.calendar import CalendarEvent, get_calendar_provider
from app.integrations.email import OutgoingEmail, render_layout
from app.models.appointment import (
    ACTIVE_STATUSES,
    ATENDIDA,
    CANCELADA,
    CONFIRMADA,
    PENDIENTE,
    TRANSITIONS,
    Appointment,
    AppointmentStatusHistory,
)
from app.models.barber import Barber
from app.models.client import Client
from app.models.service import Service
from app.models.user import ROLE_ADMIN, ROLE_BARBERO, ROLE_CAJA, ROLE_CLIENTE, User
from app.schemas.appointment import AppointmentCreateIn, AppointmentDetailOut, AppointmentOut, HistoryOut, RescheduleIn
from app.services.audit_service import audit
from app.services.availability_service import assert_slot_available, resolve_bookable
from app.services.notification_service import notify, notify_many, send_email_task
from app.services.settings_service import get_setting

logger = logging.getLogger("mrblack.appointments")

STATUS_LABEL = {PENDIENTE: "Pendiente", CONFIRMADA: "Confirmada", ATENDIDA: "Atendida", CANCELADA: "Cancelada"}
SLOT_TAKEN = "El horario acaba de ser ocupado por otra reserva. Elige otro horario."


# ------------------------------------------------------------------ permisos y presentación


def _is_staff(user: User) -> bool:
    return user.role_code in (ROLE_ADMIN, ROLE_CAJA)


def allowed_transitions(a: Appointment, user: User) -> list[str]:
    targets = set(TRANSITIONS[a.status])
    role = user.role_code
    if role == ROLE_CLIENTE:
        targets &= {CANCELADA}
    elif role == ROLE_BARBERO:
        targets &= {CONFIRMADA, ATENDIDA}
    if ATENDIDA in targets and a.start_at > datetime.now(UTC):
        targets.discard(ATENDIDA)
    return sorted(targets, key=["PENDIENTE", "CONFIRMADA", "ATENDIDA", "CANCELADA"].index)


def _can_view(a: Appointment, user: User) -> bool:
    if _is_staff(user):
        return True
    if user.role_code == ROLE_CLIENTE:
        return user.client is not None and a.client_id == user.client.id
    if user.role_code == ROLE_BARBERO:
        return user.barber is not None and a.barber_id == user.barber.id
    return False


def to_out(a: Appointment, user: User, detail: bool = False) -> AppointmentOut:
    cls = AppointmentDetailOut if detail else AppointmentOut
    out = cls.model_validate(a)
    out.allowed_transitions = allowed_transitions(a, user)
    future = a.start_at > datetime.now(UTC)
    active = a.status in ACTIVE_STATUSES
    out.can_cancel = CANCELADA in out.allowed_transitions
    out.can_reschedule = active and future and (user.role_code in (ROLE_CLIENTE, ROLE_ADMIN, ROLE_CAJA))
    out.can_charge = _is_staff(user) and a.status == ATENDIDA and a.sale_id is None
    if user.role_code != ROLE_ADMIN:
        out.google_event_id = None
    if detail:
        out.history = [HistoryOut.model_validate(h) for h in a.history]
    return out


def get_for_user(db: Session, appointment_id: int, user: User, lock: bool = False) -> Appointment:
    stmt = select(Appointment).where(Appointment.id == appointment_id)
    if lock:
        stmt = stmt.with_for_update(of=Appointment).execution_options(populate_existing=True)
    a = db.scalars(stmt).unique().first()
    if not a or not _can_view(a, user):
        # 404 también cuando no es suyo: no revela la existencia de citas ajenas.
        raise NotFound("La cita no existe.")
    return a


# ------------------------------------------------------------------ listados


SORT_COLUMNS = {
    "fecha": Appointment.start_at,
    "cliente": Client.full_name,
    "barbero": Barber.full_name,
    "servicio": Service.name,
    "estado": Appointment.status,
    "creada": Appointment.created_at,
}


def list_appointments(
    db: Session,
    user: User,
    *,
    status: str | None = None,
    barber_id: int | None = None,
    client_id: int | None = None,
    client_q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "fecha",
    order: str = "desc",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Appointment], int]:
    if date_from and date_to and date_from > date_to:
        raise BadRequest("La fecha inicial no puede ser posterior a la final.", fields={"date_from": "Rango invertido."})
    stmt = (
        select(Appointment)
        .join(Client, Client.id == Appointment.client_id)
        .join(Barber, Barber.id == Appointment.barber_id)
        .join(Service, Service.id == Appointment.service_id)
    )
    if user.role_code == ROLE_CLIENTE:
        if not user.client:
            return [], 0
        stmt = stmt.where(Appointment.client_id == user.client.id)
    elif user.role_code == ROLE_BARBERO:
        if not user.barber:
            return [], 0
        stmt = stmt.where(Appointment.barber_id == user.barber.id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    if barber_id:
        stmt = stmt.where(Appointment.barber_id == barber_id)
    if client_id:
        stmt = stmt.where(Appointment.client_id == client_id)
    if client_q:
        like = f"%{client_q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Client.full_name).like(like), Client.phone.like(like)))
    if date_from:
        stmt = stmt.where(Appointment.start_at >= day_bounds_utc(date_from)[0])
    if date_to:
        stmt = stmt.where(Appointment.start_at < day_bounds_utc(date_to)[1])

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    col = SORT_COLUMNS.get(sort, Appointment.start_at)
    direction = asc if order == "asc" else desc
    stmt = stmt.order_by(direction(col), direction(Appointment.start_at), Appointment.id)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt).unique().all()), total


# ------------------------------------------------------------------ efectos secundarios


def _event_for(a: Appointment) -> CalendarEvent:
    prefix = "" if a.status == CONFIRMADA else f"[{STATUS_LABEL[a.status]}] "
    return CalendarEvent(
        summary=f"{prefix}{a.service.name} · {a.client.full_name}",
        description=f"Barbero: {a.barber.full_name}\nCliente: {a.client.full_name} ({a.client.phone})\nCita #{a.id} · Mr Black",
        start=a.start_at.astimezone(tz()),
        end=a.end_at.astimezone(tz()),
    )


def sync_calendar_task(appointment_id: int, action: str) -> None:
    """Sincroniza con Google Calendar después del commit. Sin credenciales es un no-op."""
    db = SessionLocal()
    try:
        provider = get_calendar_provider(db)
        if not provider.enabled:
            return
        a = db.get(Appointment, appointment_id)
        if not a:
            return
        if action == "delete":
            if a.google_event_id:
                provider.delete_event(a.google_event_id)
                a.google_event_id = None
        elif a.google_event_id:
            provider.update_event(a.google_event_id, _event_for(a))
        else:
            a.google_event_id = provider.create_event(_event_for(a))
        db.commit()
    except Exception:  # noqa: BLE001 - la cita ya está guardada; solo se registra el fallo
        logger.exception("No se pudo sincronizar la cita %s con Google Calendar", appointment_id)
        db.rollback()
    finally:
        db.close()


def _fmt(a: Appointment) -> tuple[str, str]:
    local = a.start_at.astimezone(tz())
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
              "octubre", "noviembre", "diciembre"]
    return f"{days[local.weekday()]} {local.day} de {months[local.month - 1]} de {local.year}", local.strftime("%H:%M")


def _email_client(tasks: BackgroundTasks, a: Appointment, subject: str, title: str, intro: str, template: str) -> None:
    to = a.client.email or (a.client.user.email if a.client.user else None)
    if not to:
        return
    day, hour = _fmt(a)
    html, text = render_layout(
        title,
        intro,
        [
            ("Servicio", a.service.name),
            ("Barbero", a.barber.full_name),
            ("Fecha", day),
            ("Hora", hour),
            ("Precio", f"S/ {a.price:.2f}"),
            ("Estado", STATUS_LABEL[a.status]),
        ],
        ("Ver mis citas", f"{get_settings().frontend_url}/app.html#/mis-citas"),
    )
    tasks.add_task(send_email_task, OutgoingEmail(to, subject, html, text, template))


def _email_business(tasks: BackgroundTasks, a: Appointment) -> None:
    to = get_settings().notify_email
    if not to:
        return
    day, hour = _fmt(a)
    rows = [
        ("Cliente", a.client.full_name),
        ("Teléfono", a.client.phone),
        ("Servicio", a.service.name),
        ("Barbero", a.barber.full_name),
        ("Fecha", day),
        ("Hora", hour),
        ("Precio", f"S/ {a.price:.2f}"),
    ]
    if a.notes:
        rows.append(("Notas", a.notes))
    html, text = render_layout(
        "Nueva cita",
        f"{a.client.full_name} reservó {a.service.name} con {a.barber.full_name}.",
        rows,
        ("Ver citas", f"{get_settings().frontend_url}/app.html#/citas"),
    )
    tasks.add_task(send_email_task, OutgoingEmail(to, f"Nueva cita: {a.client.full_name} · {day} {hour}", html, text,
                                                  "aviso_cita_negocio"))


def _history(db: Session, a: Appointment, from_status: str | None, to_status: str, note: str | None, user: User) -> None:
    db.add(AppointmentStatusHistory(appointment_id=a.id, from_status=from_status, to_status=to_status,
                                    note=note, changed_by=user.id))


def _guard_overlap(op) -> None:
    """Traduce la violación de la restricción de exclusión (carrera entre dos reservas) a un 409 claro."""
    try:
        op()
    except IntegrityError as exc:
        db_session = getattr(op, "__self__", None)
        if db_session is not None:
            db_session.rollback()
        if "ex_appointments_no_overlap" in str(exc.orig):
            raise Conflict(SLOT_TAKEN, code="slot_taken") from None
        raise


def _commit_or_slot_taken(db: Session) -> None:
    _guard_overlap(db.commit)


def _flush_or_slot_taken(db: Session) -> None:
    _guard_overlap(db.flush)


def _assert_client_free(db: Session, client_id: int, start: datetime, end: datetime, exclude_id: int | None = None) -> None:
    q = select(func.count()).select_from(Appointment).where(
        Appointment.client_id == client_id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_at < end,
        Appointment.end_at > start,
    )
    if exclude_id:
        q = q.where(Appointment.id != exclude_id)
    if db.scalar(q):
        raise Conflict("El cliente ya tiene otra cita en ese horario.", code="client_overlap")


# ------------------------------------------------------------------ operaciones


def create_appointment(
    db: Session, data: AppointmentCreateIn, user: User, meta: RequestMeta, tasks: BackgroundTasks
) -> Appointment:
    if user.role_code == ROLE_CLIENTE:
        if not user.client:
            raise Forbidden("Tu cuenta no tiene una ficha de cliente.")
        client = user.client
    elif _is_staff(user):
        if not data.client_id:
            raise BadRequest("Selecciona el cliente de la cita.", fields={"client_id": "Selecciona un cliente."})
        client = db.get(Client, data.client_id)
        if not client or not client.is_active:
            raise NotFound("El cliente no existe.")
    else:
        raise Forbidden("Tu rol no puede registrar citas.")

    barber, service = resolve_bookable(db, data.barber_id, data.service_id)
    start = assert_slot_available(db, barber, service, data.start_at)
    end = start + timedelta(minutes=service.duration_minutes)
    _assert_client_free(db, client.id, start, end)

    a = Appointment(
        client_id=client.id,
        barber_id=barber.id,
        service_id=service.id,
        start_at=start,
        end_at=end,
        status=PENDIENTE,
        price=service.price,
        notes=data.notes,
        created_by=user.id,
    )
    db.add(a)
    _flush_or_slot_taken(db)
    _history(db, a, None, PENDIENTE, "Cita registrada", user)
    audit(db, user.id, "CITA_CREADA", "appointment", a.id,
          {"cliente": client.full_name, "barbero": barber.full_name, "servicio": service.name, "inicio": start.isoformat()}, meta)
    day, hour = _fmt(a)
    if client.user_id:
        notify(db, client.user_id, "CITA_CREADA", "Cita registrada",
               f"{service.name} con {barber.full_name} el {day} a las {hour}. Estado: pendiente de confirmación.", "#/mis-citas")
    if barber.user_id:
        notify(db, barber.user_id, "CITA_ASIGNADA", "Nueva cita asignada",
               f"{service.name} · {client.full_name} · {day} {hour}.", "#/agenda")
    if user.role_code == ROLE_CLIENTE:
        notify_many(db, active_user_ids_with_roles(db, (ROLE_CAJA,)), "CITA_POR_CONFIRMAR", "Nueva reserva por confirmar",
                    f"{client.full_name} reservó {service.name} con {barber.full_name} el {day} {hour}.", "#/citas")
    _commit_or_slot_taken(db)
    db.refresh(a)

    _email_client(tasks, a, "Tu cita en Mr Black fue registrada", "Cita registrada",
                  f"Hola {client.full_name}, registramos tu cita. Te avisaremos cuando sea confirmada.", "cita_creada")
    _email_business(tasks, a)
    tasks.add_task(sync_calendar_task, a.id, "upsert")
    return a


def change_status(
    db: Session, appointment_id: int, to_status: str, note: str | None, user: User, meta: RequestMeta, tasks: BackgroundTasks
) -> Appointment:
    a = get_for_user(db, appointment_id, user, lock=True)
    from_status = a.status
    if to_status == from_status:
        raise BadRequest(f"La cita ya está en estado {STATUS_LABEL[to_status].lower()}.")
    if to_status not in TRANSITIONS[from_status]:
        if from_status in (ATENDIDA, CANCELADA):
            raise Conflict(f"La cita está {STATUS_LABEL[from_status].lower()} y ya no puede modificarse.", code="final_status")
        raise Conflict(
            f"No se puede pasar de {STATUS_LABEL[from_status].lower()} a {STATUS_LABEL[to_status].lower()}.",
            code="invalid_transition",
        )
    if to_status not in allowed_transitions(a, user):
        if to_status == ATENDIDA and a.start_at > datetime.now(UTC):
            raise BadRequest("No se puede marcar como atendida antes de la fecha y hora de la cita.", code="not_started")
        raise Forbidden("Tu rol no puede realizar este cambio de estado.")
    if to_status == CANCELADA and user.role_code == ROLE_CLIENTE:
        _check_client_cancel_window(db, a)
        if a.start_at <= datetime.now(UTC):
            raise BadRequest("No puedes cancelar una cita que ya comenzó.")

    a.status = to_status
    if to_status == CANCELADA:
        a.cancel_reason = note
    _history(db, a, from_status, to_status, note, user)
    audit(db, user.id, f"CITA_{to_status}", "appointment", a.id, {"de": from_status, "a": to_status, "nota": note}, meta)

    day, hour = _fmt(a)
    title = {CONFIRMADA: "Cita confirmada", ATENDIDA: "Cita atendida", CANCELADA: "Cita cancelada"}[to_status]
    if a.client.user_id and a.client.user_id != user.id:
        notify(db, a.client.user_id, f"CITA_{to_status}", title, f"{a.service.name} con {a.barber.full_name} el {day} a las {hour}.", "#/mis-citas")
    if a.barber.user_id and a.barber.user_id != user.id and to_status != ATENDIDA:
        notify(db, a.barber.user_id, f"CITA_{to_status}", title, f"{a.service.name} · {a.client.full_name} · {day} {hour}.", "#/agenda")
    if to_status == CANCELADA and user.role_code == ROLE_CLIENTE:
        notify_many(db, active_user_ids_with_roles(db, (ROLE_CAJA,)), "CITA_CANCELADA", "Cita cancelada por el cliente",
                    f"{a.client.full_name} canceló {a.service.name} del {day} {hour}.", "#/citas")
    db.commit()
    db.refresh(a)

    if to_status == CONFIRMADA:
        _email_client(tasks, a, "Tu cita en Mr Black está confirmada", "¡Cita confirmada!",
                      f"Hola {a.client.full_name}, tu cita fue confirmada. Te esperamos.", "cita_confirmada")
        tasks.add_task(sync_calendar_task, a.id, "upsert")
    elif to_status == CANCELADA:
        _email_client(tasks, a, "Tu cita en Mr Black fue cancelada", "Cita cancelada",
                      f"Hola {a.client.full_name}, tu cita fue cancelada." + (f" Motivo: {note}" if note else ""), "cita_cancelada")
        tasks.add_task(sync_calendar_task, a.id, "delete")
    else:
        tasks.add_task(sync_calendar_task, a.id, "upsert")
    return a


def _check_client_cancel_window(db: Session, a: Appointment) -> None:
    hours = int(get_setting(db, "booking")["client_cancel_min_hours"])
    if a.start_at - datetime.now(UTC) < timedelta(hours=hours):
        raise BadRequest(
            f"Solo puedes cancelar o reprogramar con al menos {hours} hora(s) de anticipación. Comunícate con la barbería.",
            code="too_late",
        )


def reschedule(
    db: Session, appointment_id: int, data: RescheduleIn, user: User, meta: RequestMeta, tasks: BackgroundTasks
) -> Appointment:
    """Reprogramación atómica: la cita conserva su identidad e historial y solo cambia si el
    nuevo horario se valida y se guarda (corrige el defecto P5 del prototipo)."""
    a = get_for_user(db, appointment_id, user, lock=True)
    if user.role_code not in (ROLE_CLIENTE, ROLE_ADMIN, ROLE_CAJA):
        raise Forbidden("Tu rol no puede reprogramar citas.")
    if a.status not in ACTIVE_STATUSES:
        raise Conflict(f"La cita está {STATUS_LABEL[a.status].lower()} y no puede reprogramarse.", code="final_status")
    if a.start_at <= datetime.now(UTC):
        raise BadRequest("No se puede reprogramar una cita que ya comenzó o pasó.")
    if user.role_code == ROLE_CLIENTE:
        _check_client_cancel_window(db, a)

    barber_id = data.barber_id or a.barber_id
    barber, service = resolve_bookable(db, barber_id, a.service_id)
    start = assert_slot_available(db, barber, service, data.start_at, exclude_appointment_id=a.id)
    if start == a.start_at and barber.id == a.barber_id:
        raise BadRequest("Selecciona un horario distinto al actual.")
    end = start + timedelta(minutes=service.duration_minutes)
    _assert_client_free(db, a.client_id, start, end, exclude_id=a.id)

    old_start, old_barber = a.start_at, a.barber
    old_day, old_hour = _fmt(a)
    a.start_at, a.end_at, a.barber_id = start, end, barber.id
    _flush_or_slot_taken(db)
    db.refresh(a)
    new_day, new_hour = _fmt(a)
    note = f"Reprogramada del {old_day} {old_hour} al {new_day} {new_hour}"
    if old_barber.id != barber.id:
        note += f" (barbero: {old_barber.full_name} → {barber.full_name})"
    _history(db, a, a.status, a.status, note, user)
    audit(db, user.id, "CITA_REPROGRAMADA", "appointment", a.id,
          {"inicio_anterior": old_start.isoformat(), "inicio_nuevo": start.isoformat(),
           "barbero_anterior": old_barber.id, "barbero_nuevo": barber.id}, meta)
    if a.client.user_id and a.client.user_id != user.id:
        notify(db, a.client.user_id, "CITA_REPROGRAMADA", "Cita reprogramada", note + ".", "#/mis-citas")
    for uid in {old_barber.user_id, barber.user_id} - {None, user.id}:
        notify(db, uid, "CITA_REPROGRAMADA", "Cita reprogramada", f"{a.client.full_name}: {note}.", "#/agenda")
    if user.role_code == ROLE_CLIENTE:
        notify_many(db, active_user_ids_with_roles(db, (ROLE_CAJA,)), "CITA_REPROGRAMADA", "Cita reprogramada por el cliente",
                    f"{a.client.full_name}: {note}.", "#/citas")
    _commit_or_slot_taken(db)
    db.refresh(a)

    _email_client(tasks, a, "Tu cita en Mr Black fue reprogramada", "Cita reprogramada",
                  f"Hola {a.client.full_name}, tu cita fue reprogramada. Antes: {old_day} a las {old_hour}.", "cita_reprogramada")
    tasks.add_task(sync_calendar_task, a.id, "upsert")
    return a
