"""Recordatorio previo a la cita (REMINDERS_ENABLED=true, REMINDER_MINUTES=10).

Cada ciclo busca citas PENDIENTE o CONFIRMADA que empiezan dentro de los próximos
REMINDER_MINUTES minutos y aún no tienen recordatorio. Las bloquea con FOR UPDATE SKIP LOCKED,
las marca (reminder_sent_at) y crea las notificaciones de la campana en la MISMA transacción:
si hay varios procesos de la API, cada cita la toma solo uno y el aviso nunca se duplica.
Los correos se envían después del commit; un fallo de correo se registra y no detiene el ciclo.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations.email import OutgoingEmail, render_layout
from app.models.appointment import ACTIVE_STATUSES, Appointment
from app.services.notification_service import notify, send_email_task

logger = logging.getLogger("mrblack.reminders")

INTERVAL_SECONDS = 60
BATCH = 200


def _fmt(a: Appointment) -> tuple[str, str]:
    from app.services.appointment_service import _fmt as fmt  # import diferido: evita ciclos

    return fmt(a)


def _reminder_email(a: Appointment, minutes: int) -> OutgoingEmail | None:
    to = a.client.email or (a.client.user.email if a.client.user else None)
    if not to:
        return None
    day, hour = _fmt(a)
    html, text = render_layout(
        f"Tu cita empieza en {minutes} minutos",
        f"Hola {a.client.full_name}, te esperamos en Mr Black.",
        [("Servicio", a.service.name), ("Barbero", a.barber.full_name), ("Fecha", day), ("Hora", hour)],
        ("Ver mis citas", f"{get_settings().frontend_url}/app.html#/mis-citas"),
    )
    return OutgoingEmail(to, f"Tu cita en Mr Black empieza en {minutes} minutos", html, text, "cita_recordatorio")


def run_once(now: datetime | None = None) -> int:
    """Procesa las citas que vencen ahora. Devuelve cuántos recordatorios se registraron."""
    minutes = get_settings().reminder_minutes
    now = now or datetime.now(UTC)
    emails: list[OutgoingEmail] = []
    db = SessionLocal()
    try:
        # Solo la columna id: con las relaciones "joined" de Appointment, FOR UPDATE fallaría
        # sobre el lado nulo de un OUTER JOIN.
        ids = db.scalars(
            select(Appointment.id)
            .where(
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.reminder_sent_at.is_(None),
                Appointment.start_at > now,
                Appointment.start_at <= now + timedelta(minutes=minutes),
            )
            .order_by(Appointment.start_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        ).all()
        if not ids:
            db.rollback()
            return 0
        appointments = db.scalars(select(Appointment).where(Appointment.id.in_(ids))).unique().all()
        for a in appointments:
            a.reminder_sent_at = now
            day, hour = _fmt(a)
            title = f"Tu cita empieza en {minutes} min"
            if a.client.user_id:
                notify(db, a.client.user_id, "CITA_RECORDATORIO", title,
                       f"{a.service.name} con {a.barber.full_name} hoy a las {hour}.", "#/mis-citas")
            if a.barber.user_id:
                notify(db, a.barber.user_id, "CITA_RECORDATORIO", f"Cita en {minutes} min",
                       f"{a.service.name} · {a.client.full_name} · {day} {hour}.", "#/agenda")
            email = _reminder_email(a, minutes)
            if email:
                emails.append(email)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    for email in emails:
        send_email_task(email)  # registra ENVIADO/ERROR en el log de correos; nunca lanza
    logger.info("Recordatorios enviados: %s", len(ids))
    return len(ids)


async def reminder_loop(interval: int = INTERVAL_SECONDS) -> None:
    """Tarea de fondo iniciada en el lifespan de FastAPI."""
    logger.info("Recordatorios activos: %s min antes, revisión cada %s s.", get_settings().reminder_minutes, interval)
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:  # noqa: BLE001 - un error (p. ej. BD caída) no detiene los ciclos siguientes
            logger.exception("Fallo en el ciclo de recordatorios")
        await asyncio.sleep(interval)
