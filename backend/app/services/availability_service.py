"""Cálculo de disponibilidad real desde la base de datos.

Un horario está disponible solo si:
- el barbero está activo, acepta reservas y ofrece el servicio (activo);
- el día es laborable según su horario semanal;
- el servicio completo cabe dentro del horario y no cruza el descanso;
- no cae en un bloqueo (vacaciones / día no laborable puntual);
- no se solapa con otra cita activa del barbero;
- empieza después de "ahora + anticipación mínima" (zona horaria de la barbería).

La base de datos refuerza la regla de solapamiento con una restricción de exclusión.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, NotFound
from app.core.timeutils import local_dt, now_local, today_local, tz
from app.models.appointment import ACTIVE_STATUSES, Appointment
from app.models.barber import Barber, BarberSchedule, BarberTimeOff
from app.models.service import Service
from app.services.settings_service import get_setting

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@dataclass
class Slot:
    time: str
    start_at: datetime
    available: bool
    reason: str | None = None


@dataclass
class DayAvailability:
    working: bool
    message: str | None
    slots: list[Slot]


def resolve_bookable(db: Session, barber_id: int, service_id: int) -> tuple[Barber, Service]:
    barber = db.get(Barber, barber_id)
    if not barber or not barber.is_active:
        raise NotFound("El barbero no existe o no está activo.")
    service = db.get(Service, service_id)
    if not service or not service.is_active:
        raise NotFound("El servicio no existe o no está disponible.")
    if not barber.is_available:
        raise BadRequest("El barbero no está recibiendo reservas en este momento.", code="barber_unavailable")
    if service.id not in {s.id for s in barber.services}:
        raise BadRequest("El barbero seleccionado no realiza este servicio.", code="service_not_offered")
    return barber, service


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def day_availability(
    db: Session,
    barber: Barber,
    service: Service,
    day: date,
    exclude_appointment_id: int | None = None,
) -> DayAvailability:
    booking = get_setting(db, "booking")
    interval = int(booking["slot_interval_minutes"])
    min_notice = int(booking["min_notice_minutes"])
    max_days = int(booking["max_days_ahead"])

    today = today_local()
    if day < today:
        return DayAvailability(False, "No puedes reservar en una fecha pasada.", [])
    if day > today + timedelta(days=max_days):
        return DayAvailability(False, f"Solo se puede reservar con hasta {max_days} días de anticipación.", [])

    schedule = db.scalars(
        select(BarberSchedule).where(BarberSchedule.barber_id == barber.id, BarberSchedule.weekday == day.weekday())
    ).first()
    if not schedule:
        return DayAvailability(False, f"{barber.full_name} no atiende los {WEEKDAYS[day.weekday()]}.", [])

    day_start = local_dt(day, schedule.start_time)
    day_end = local_dt(day, schedule.end_time)
    duration = timedelta(minutes=service.duration_minutes)

    time_off = db.scalars(
        select(BarberTimeOff).where(
            BarberTimeOff.barber_id == barber.id, BarberTimeOff.start_at < day_end, BarberTimeOff.end_at > day_start
        )
    ).all()
    if any(t.start_at <= day_start and t.end_at >= day_end for t in time_off):
        reason = next((t.reason for t in time_off if t.reason), None)
        return DayAvailability(False, f"{barber.full_name} no está disponible ese día" + (f" ({reason})." if reason else "."), [])

    busy_q = select(Appointment.start_at, Appointment.end_at).where(
        Appointment.barber_id == barber.id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_at < day_end,
        Appointment.end_at > day_start,
    )
    if exclude_appointment_id:
        busy_q = busy_q.where(Appointment.id != exclude_appointment_id)
    busy = db.execute(busy_q).all()

    brk = None
    if schedule.break_start and schedule.break_end:
        brk = (local_dt(day, schedule.break_start), local_dt(day, schedule.break_end))

    earliest = now_local() + timedelta(minutes=min_notice)
    slots: list[Slot] = []
    cursor = day_start
    while cursor + duration <= day_end:
        end = cursor + duration
        if brk and _overlaps(cursor, end, *brk):
            cursor += timedelta(minutes=interval)
            continue  # el descanso no se ofrece como horario
        reason = None
        if cursor < earliest:
            reason = "pasado"
        elif any(_overlaps(cursor, end, t.start_at, t.end_at) for t in time_off):
            reason = "bloqueado"
        elif any(_overlaps(cursor, end, b.start_at, b.end_at) for b in busy):
            reason = "ocupado"
        slots.append(Slot(cursor.strftime("%H:%M"), cursor, reason is None, reason))
        cursor += timedelta(minutes=interval)

    message = None
    if slots and not any(s.available for s in slots):
        message = "No quedan horarios disponibles para esta fecha."
    return DayAvailability(True, message, slots)


SLOT_REASON_MESSAGES = {
    "pasado": "La fecha y hora seleccionadas ya pasaron. Elige un horario posterior a la hora actual.",
    "bloqueado": "El barbero no está disponible en ese horario.",
    "ocupado": "Ese horario ya está ocupado. Elige otro.",
}


def assert_slot_available(
    db: Session, barber: Barber, service: Service, start_at: datetime, exclude_appointment_id: int | None = None
) -> datetime:
    """Valida en el servidor que `start_at` sea uno de los horarios disponibles calculados."""
    start_local = (start_at if start_at.tzinfo else start_at.replace(tzinfo=tz())).astimezone(tz())
    if start_local.astimezone(UTC) <= datetime.now(UTC):
        raise BadRequest(SLOT_REASON_MESSAGES["pasado"], code="slot_in_past")
    day = day_availability(db, barber, service, start_local.date(), exclude_appointment_id)
    if not day.working:
        raise BadRequest(day.message or "El barbero no atiende en esa fecha.", code="slot_not_working")
    match = next((s for s in day.slots if s.start_at == start_local), None)
    if match is None:
        raise BadRequest(
            "El horario elegido está fuera del horario de atención del barbero o el servicio no alcanza a terminar antes del cierre.",
            code="slot_out_of_schedule",
        )
    if not match.available:
        raise BadRequest(SLOT_REASON_MESSAGES.get(match.reason or "", "Horario no disponible."), code=f"slot_{match.reason}")
    return start_local
