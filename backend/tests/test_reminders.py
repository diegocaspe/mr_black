"""Recordatorio X minutos antes de la cita: un solo envío, solo citas activas y futuras,
bloqueo atómico entre procesos (FOR UPDATE SKIP LOCKED) y reinicio al reprogramar."""

from datetime import datetime, timedelta

from sqlalchemy import select, text

from app.core.database import SessionLocal, engine
from app.models.notification import Notification
from app.services.reminder_service import run_once
from tests.conftest import future_weekday, slot

SUBJECT = "Tu cita en Mr Black empieza en 10 minutos"


def _book(cliente, hhmm="10:00", weekday=2):
    r = cliente.post("/api/appointments", {"service_id": 1, "barber_id": 1, "start_at": slot(future_weekday(weekday), hhmm)})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], datetime.fromisoformat(body["start_at"])


def _reminders(outbox):
    return [e for e in outbox if e.template == "cita_recordatorio"]


def _reminder_notifications():
    with SessionLocal() as db:
        return db.scalars(select(Notification).where(Notification.type == "CITA_RECORDATORIO")).all()


def test_reminder_sent_once_with_email_and_bell(cliente, outbox):
    aid, start = _book(cliente)
    assert run_once(now=start - timedelta(minutes=5)) == 1

    emails = _reminders(outbox)
    assert len(emails) == 1
    assert emails[0].subject == SUBJECT and emails[0].to == "carlos.mendoza@example.com"
    assert "Adriano Vargas" in emails[0].text and "Corte" in emails[0].text and "10:00" in emails[0].text
    # Campana: el cliente (usuario de Carlos) y el barbero (usuario de barbero1).
    notes = _reminder_notifications()
    assert len(notes) == 2
    with engine.connect() as conn:
        ids = set(conn.execute(text("SELECT id FROM users WHERE username IN ('987654321', 'barbero1')")).scalars())
        assert conn.execute(text("SELECT reminder_sent_at IS NOT NULL FROM appointments WHERE id = :i"), {"i": aid}).scalar()
    assert {n.user_id for n in notes} == ids

    # Ciclos siguientes: no se repite.
    assert run_once(now=start - timedelta(minutes=4)) == 0
    assert run_once(now=start - timedelta(minutes=1)) == 0
    assert len(_reminders(outbox)) == 1 and len(_reminder_notifications()) == 2


def test_no_reminder_too_early_past_or_cancelled(cliente, outbox):
    aid, start = _book(cliente)
    assert run_once(now=start - timedelta(minutes=30)) == 0  # todavía falta
    assert run_once(now=start + timedelta(minutes=1)) == 0  # ya empezó

    cliente.patch(f"/api/appointments/{aid}/status", {"status": "CANCELADA", "note": "No puedo ir"})
    assert run_once(now=start - timedelta(minutes=5)) == 0  # cancelada
    assert _reminders(outbox) == [] and _reminder_notifications() == []


def test_confirmed_appointment_gets_reminder(cliente, caja, outbox):
    aid, start = _book(cliente)
    assert caja.patch(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}).status_code == 200
    assert run_once(now=start - timedelta(minutes=10)) == 1  # justo en el límite de 10 minutos
    assert len(_reminders(outbox)) == 1


def test_row_locked_by_another_process_is_skipped(cliente, outbox):
    """Otro proceso que ya tomó la cita (fila bloqueada) impide el envío duplicado."""
    aid, start = _book(cliente)
    with engine.connect() as other:
        tx = other.begin()
        other.execute(text("SELECT id FROM appointments WHERE id = :i FOR UPDATE"), {"i": aid})
        assert run_once(now=start - timedelta(minutes=5)) == 0  # SKIP LOCKED: no espera ni duplica
        tx.rollback()
    assert run_once(now=start - timedelta(minutes=5)) == 1
    assert len(_reminders(outbox)) == 1


def test_email_failure_does_not_stop_the_cycle(cliente, monkeypatch):
    _, start = _book(cliente)

    class Broken:
        def send(self, email):
            raise ConnectionError("proveedor caído")

    monkeypatch.setattr("app.services.notification_service.get_email_sender", lambda: Broken())
    assert run_once(now=start - timedelta(minutes=5)) == 1
    with engine.connect() as conn:
        status, error = conn.execute(text(
            "SELECT status, error FROM email_log WHERE template = 'cita_recordatorio'")).one()
    assert status == "ERROR" and "proveedor caído" in error
    assert len(_reminder_notifications()) == 2  # la campana sí se registró


def test_reschedule_resets_reminder(cliente, outbox):
    aid, start = _book(cliente)
    assert run_once(now=start - timedelta(minutes=5)) == 1
    r = cliente.post(f"/api/appointments/{aid}/reschedule", {"start_at": slot(future_weekday(3), "11:00")})
    assert r.status_code == 200, r.text
    new_start = datetime.fromisoformat(r.json()["start_at"])
    assert run_once(now=new_start - timedelta(minutes=5)) == 1
    assert len(_reminders(outbox)) == 2
