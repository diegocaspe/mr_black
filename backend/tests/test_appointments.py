"""Citas: disponibilidad, doble reserva, estados, reprogramación y filtros
(0022585, 0022625, 0022600 y prevención de doble reserva)."""

import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import engine
from app.core.timeutils import now_local, today_local
from tests.conftest import Api, future_weekday, slot

WED = None


@pytest.fixture
def wed():
    return future_weekday(2)


def book(api, d, hhmm, service=1, barber=1, client_id=None):
    body = {"service_id": service, "barber_id": barber, "start_at": slot(d, hhmm)}
    if client_id:
        body["client_id"] = client_id
    return api.post("/api/appointments", body)


# ------------------------------------------------------------------ disponibilidad
def test_availability_respects_schedule_and_break(anon, wed):
    av = anon.get("/api/availability", params={"barber_id": 1, "service_id": 1, "date": wed.isoformat()}).json()
    times = [s["time"] for s in av["slots"]]
    assert av["working"] and times[0] == "09:00"
    assert "12:30" not in times and "13:00" not in times and "13:30" not in times  # cruzan el descanso 13–14
    assert "14:00" in times
    assert times[-1] == "18:30"  # 45 min deben terminar antes de las 19:30


def test_sunday_is_not_working(anon):
    av = anon.get("/api/availability", params={"barber_id": 1, "service_id": 1, "date": future_weekday(6).isoformat()}).json()
    assert av["working"] is False and av["slots"] == []


def test_unavailable_barber_and_service_not_offered(anon, wed):
    assert anon.get("/api/availability", params={"barber_id": 3, "service_id": 1, "date": wed.isoformat()}).status_code == 400
    assert anon.get("/api/availability", params={"barber_id": 2, "service_id": 4, "date": wed.isoformat()}).status_code == 400


def test_cannot_book_past_time_same_day(cliente):
    """0022585: una hora ya pasada del mismo día se rechaza en el servidor."""
    past = now_local() - timedelta(hours=1)
    r = cliente.post("/api/appointments", {"service_id": 1, "barber_id": 1, "start_at": past.replace(minute=0, second=0, microsecond=0).isoformat()})
    assert r.status_code == 400 and r.json()["error"]["code"] == "slot_in_past"
    av = cliente.get("/api/availability", params={"barber_id": 1, "service_id": 1, "date": today_local().isoformat()}).json()
    now = now_local()
    for s in av["slots"]:
        if datetime.fromisoformat(s["start_at"]) <= now:
            assert s["available"] is False


def test_cannot_book_outside_schedule_or_unaligned(cliente, wed):
    assert book(cliente, wed, "20:00").status_code == 400
    assert book(cliente, wed, "13:00").status_code == 400  # descanso
    assert book(cliente, wed, "18:45").status_code == 400  # el servicio excede el horario
    assert book(cliente, wed, "09:10").status_code == 400  # no coincide con un horario ofrecido


def test_book_ok_creates_pending_and_notifies(cliente, barbero, caja, outbox, wed):
    r = book(cliente, wed, "10:00")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "PENDIENTE" and a["price"] == "35.00"
    assert any("registrada" in e.subject for e in outbox)
    assert any(n["type"] == "CITA_ASIGNADA" for n in barbero.get("/api/notifications").json())
    assert any(n["type"] == "CITA_POR_CONFIRMAR" for n in caja.get("/api/notifications").json())


def test_new_booking_emails_business_inbox(cliente, outbox, wed, monkeypatch):
    monkeypatch.setattr(get_settings(), "notify_email", "avisos@mrblack.test")
    assert book(cliente, wed, "10:00").status_code == 201
    aviso = next(e for e in outbox if e.to == "avisos@mrblack.test")
    assert aviso.subject.startswith("Nueva cita") and aviso.template == "aviso_cita_negocio"


def test_double_booking_same_slot_rejected(cliente, cliente2, wed):
    assert book(cliente, wed, "10:00").status_code == 201
    r = book(cliente2, wed, "10:00")
    assert r.status_code == 400 and r.json()["error"]["code"] == "slot_ocupado"


def test_overlapping_duration_blocks_following_slots(cliente, cliente2, wed):
    assert book(cliente, wed, "10:00", service=3).status_code == 201  # Corte + Barba 70 min → 10:00–11:10
    assert book(cliente2, wed, "10:30").status_code == 400
    assert book(cliente2, wed, "11:00").status_code == 400
    assert book(cliente2, wed, "09:30").status_code == 400  # 09:30–10:15 se solapa
    assert book(cliente2, wed, "11:30").status_code == 201
    av = cliente2.get("/api/availability", params={"barber_id": 1, "service_id": 1, "date": wed.isoformat()}).json()
    status = {s["time"]: s["reason"] for s in av["slots"]}
    assert status["10:00"] == "ocupado" and status["10:30"] == "ocupado"


def test_concurrent_booking_only_one_wins(as_user, wed):
    """Dos clientes reservan el mismo horario al mismo tiempo: solo uno lo consigue."""
    clients = [as_user("987654321"), as_user("999888777")]
    barrier = threading.Barrier(2)
    results = []

    def run(api):
        barrier.wait()
        results.append(book(api, wed, "15:00").status_code)

    threads = [threading.Thread(target=run, args=(c,)) for c in clients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results)[0] == 201 and results.count(201) == 1, results


def test_database_exclusion_constraint_blocks_overlap(wed):
    """Aunque se salte la API, PostgreSQL impide dos citas activas solapadas del mismo barbero."""
    start = f"{wed}T16:00:00-05:00"
    insert = text(
        "INSERT INTO appointments (client_id, barber_id, service_id, start_at, end_at, status, price) "
        "VALUES (:c, 1, 1, :s, CAST(:s AS timestamptz) + interval '45 minutes', 'PENDIENTE', 35)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"c": 1, "s": start})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert, {"c": 2, "s": f"{wed}T16:30:00-05:00"})


def test_exclusion_constraint_is_the_one_rejecting_overlaps(wed):
    """Cita A 19:00–20:00 se acepta y B 19:30–20:30 (mismo barbero) la rechaza PostgreSQL por
    `ex_appointments_no_overlap`, sin pasar por la API. Los casos legítimos siguen permitidos."""
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")) == 1
        assert conn.scalar(text(
            "SELECT contype FROM pg_constraint WHERE conname = 'ex_appointments_no_overlap'"
        )) == "x"

    insert = text(
        "INSERT INTO appointments (client_id, barber_id, service_id, start_at, end_at, status, price) "
        "VALUES (:c, :b, 1, CAST(:s AS timestamptz), CAST(:e AS timestamptz), :st, 35)"
    )

    def at(hhmm):
        return f"{wed}T{hhmm}:00-05:00"

    with engine.begin() as conn:  # Cita A → aceptada
        conn.execute(insert, {"c": 1, "b": 1, "s": at("19:00"), "e": at("20:00"), "st": "PENDIENTE"})

    for status in ("PENDIENTE", "CONFIRMADA"):  # Cita B → rechazada por la restricción de exclusión
        with pytest.raises(IntegrityError) as exc:
            with engine.begin() as conn:
                conn.execute(insert, {"c": 2, "b": 1, "s": at("19:30"), "e": at("20:30"), "st": status})
        assert exc.value.orig.diag.constraint_name == "ex_appointments_no_overlap"

    with engine.begin() as conn:
        # Permitidos: rango contiguo ('[)'), otro barbero y citas no activas en el mismo horario.
        conn.execute(insert, {"c": 2, "b": 1, "s": at("20:00"), "e": at("20:30"), "st": "PENDIENTE"})
        conn.execute(insert, {"c": 3, "b": 2, "s": at("19:30"), "e": at("20:30"), "st": "CONFIRMADA"})
        conn.execute(insert, {"c": 2, "b": 1, "s": at("19:30"), "e": at("20:30"), "st": "CANCELADA"})

    with pytest.raises(IntegrityError) as exc:  # Reactivar una cancelada solapada también se rechaza
        with engine.begin() as conn:
            conn.execute(text("UPDATE appointments SET status = 'PENDIENTE' "
                              "WHERE barber_id = 1 AND status = 'CANCELADA' AND start_at = CAST(:s AS timestamptz)"),
                         {"s": at("19:30")})
    assert exc.value.orig.diag.constraint_name == "ex_appointments_no_overlap"


def test_client_cannot_have_two_overlapping_appointments(cliente, wed):
    assert book(cliente, wed, "10:00", barber=1).status_code == 201
    r = book(cliente, wed, "10:00", barber=2)
    assert r.status_code == 409 and r.json()["error"]["code"] == "client_overlap"


def test_staff_registers_appointment_for_client(caja, wed):
    assert book(caja, wed, "10:00").status_code == 400  # falta cliente
    r = book(caja, wed, "10:00", client_id=3)
    assert r.status_code == 201 and r.json()["client"]["id"] == 3


# ------------------------------------------------------------------ estados (0022625)
def _new(api, d, hhmm="10:00", client_id=None):
    r = book(api, d, hhmm, client_id=client_id)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_valid_transitions(caja, wed):
    aid = _new(caja, wed, client_id=1)
    assert caja.patch(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}).json()["status"] == "CONFIRMADA"
    r = caja.patch(f"/api/appointments/{aid}/status", {"status": "ATENDIDA"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_started"  # aún no llega la hora
    assert caja.patch(f"/api/appointments/{aid}/status", {"status": "CANCELADA", "note": "Cliente avisó"}).json()["status"] == "CANCELADA"


def test_pending_cannot_jump_to_attended(caja):
    # Cita pasada pendiente (seed) para probar transición inválida directa
    items = caja.get("/api/appointments", params={"status": "PENDIENTE"}).json()["items"]
    r = caja.patch(f"/api/appointments/{items[0]['id']}/status", {"status": "ATENDIDA"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


def test_attended_and_cancelled_are_final(caja):
    attended = caja.get("/api/appointments", params={"status": "ATENDIDA"}).json()["items"][0]["id"]
    for target in ("PENDIENTE", "CONFIRMADA", "CANCELADA"):
        r = caja.patch(f"/api/appointments/{attended}/status", {"status": target})
        assert r.status_code == 409 and r.json()["error"]["code"] in ("final_status", "invalid_transition"), target
    cancelled = caja.get("/api/appointments", params={"status": "CANCELADA"}).json()["items"][0]["id"]
    for target in ("PENDIENTE", "CONFIRMADA", "ATENDIDA"):
        assert caja.patch(f"/api/appointments/{cancelled}/status", {"status": target}).status_code == 409


def test_confirmed_past_can_be_attended(caja, admin):
    a = next(x for x in caja.get("/api/appointments", params={"page_size": 100}).json()["items"] if x["status"] == "CONFIRMADA")
    # Fuerza una cita confirmada en el pasado para simular el día de la atención.
    with engine.begin() as conn:
        conn.execute(text("UPDATE appointments SET start_at = now() - interval '2 hours', end_at = now() - interval '1 hour' WHERE id = :i"), {"i": a["id"]})
    r = caja.patch(f"/api/appointments/{a['id']}/status", {"status": "ATENDIDA"})
    assert r.status_code == 200 and r.json()["can_charge"] is True
    hist = admin.get(f"/api/appointments/{a['id']}").json()["history"]
    assert [h["to_status"] for h in hist][-1] == "ATENDIDA"


def test_barber_can_confirm_own_but_not_cancel(barbero, cliente, wed):
    aid = _new(cliente, wed)
    assert barbero.patch(f"/api/appointments/{aid}/status", {"status": "CANCELADA"}).status_code == 403
    assert barbero.patch(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}).status_code == 200


def test_client_cancels_own_and_slot_is_freed(cliente, cliente2, outbox, wed):
    aid = _new(cliente, wed)
    r = cliente.post(f"/api/appointments/{aid}/cancel", {"reason": "Viaje"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELADA"
    assert any("cancelada" in e.subject for e in outbox)
    assert book(cliente2, wed, "10:00").status_code == 201
    assert cliente.patch(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}).status_code == 409


def test_client_cannot_confirm_own(cliente, wed):
    aid = _new(cliente, wed)
    assert cliente.patch(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}).status_code == 403


# ------------------------------------------------------------------ reprogramación
def test_reschedule_is_atomic_and_keeps_history(cliente, outbox, wed):
    aid = _new(cliente, wed)
    r = cliente.post(f"/api/appointments/{aid}/reschedule", {"start_at": slot(wed, "16:00")})
    assert r.status_code == 200 and r.json()["id"] == aid and r.json()["status"] == "PENDIENTE"
    assert "T16:00:00" in r.json()["start_at"] or "T21:00:00" in r.json()["start_at"]
    detail = cliente.get(f"/api/appointments/{aid}").json()
    assert "Reprogramada" in detail["history"][-1]["note"]
    assert any("reprogramada" in e.subject for e in outbox)
    # el horario anterior quedó libre
    av = cliente.get("/api/availability", params={"barber_id": 1, "service_id": 1, "date": wed.isoformat()}).json()
    assert next(s for s in av["slots"] if s["time"] == "10:00")["available"] is True


def test_failed_reschedule_keeps_original(cliente, cliente2, wed):
    aid = _new(cliente, wed)
    _new(cliente2, wed, "16:00")
    r = cliente.post(f"/api/appointments/{aid}/reschedule", {"start_at": slot(wed, "16:00")})
    assert r.status_code == 400
    a = cliente.get(f"/api/appointments/{aid}").json()
    assert a["status"] == "PENDIENTE" and ("T10:00:00" in a["start_at"] or "T15:00:00" in a["start_at"])


def test_reschedule_final_status_rejected(caja):
    attended = caja.get("/api/appointments", params={"status": "ATENDIDA"}).json()["items"][0]["id"]
    assert caja.post(f"/api/appointments/{attended}/reschedule", {"start_at": slot(future_weekday(2), "10:00")}).status_code == 409


# ------------------------------------------------------------------ filtros y orden (0022600)
def test_filters_and_sorting(caja, wed):
    _new(caja, wed, "10:00", client_id=3)
    by_status = caja.get("/api/appointments", params={"status": "ATENDIDA"}).json()
    assert by_status["total"] >= 1 and all(a["status"] == "ATENDIDA" for a in by_status["items"])
    by_barber = caja.get("/api/appointments", params={"barber_id": 2}).json()["items"]
    assert by_barber and all(a["barber"]["id"] == 2 for a in by_barber)
    by_client = caja.get("/api/appointments", params={"client": "ramírez"}).json()["items"]
    assert by_client and all(a["client"]["id"] == 3 for a in by_client)
    by_phone = caja.get("/api/appointments", params={"client": "988111"}).json()["items"]
    assert len(by_phone) == len(by_client)
    in_range = caja.get("/api/appointments", params={"date_from": wed.isoformat(), "date_to": wed.isoformat()}).json()["items"]
    assert len(in_range) == 1
    names = [a["client"]["full_name"] for a in caja.get("/api/appointments", params={"sort": "cliente", "order": "asc", "page_size": 100}).json()["items"]]
    assert names == sorted(names)
    statuses = [a["status"] for a in caja.get("/api/appointments", params={"sort": "estado", "order": "desc", "page_size": 100}).json()["items"]]
    assert statuses == sorted(statuses, reverse=True)
    services = [a["service"]["name"] for a in caja.get("/api/appointments", params={"sort": "servicio", "order": "asc", "page_size": 100}).json()["items"]]
    assert services == sorted(services)
    dates = [a["start_at"] for a in caja.get("/api/appointments", params={"sort": "fecha", "order": "asc", "page_size": 100}).json()["items"]]
    assert [datetime.fromisoformat(x) for x in dates] == sorted(datetime.fromisoformat(x) for x in dates)
    assert caja.get("/api/appointments", params={"date_from": "2026-05-10", "date_to": "2026-05-01"}).status_code == 400
    page = caja.get("/api/appointments", params={"page_size": 2, "page": 2}).json()
    assert page["page"] == 2 and len(page["items"]) <= 2
