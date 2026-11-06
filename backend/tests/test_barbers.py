"""Barberos: validación, rating exacto, persistencia real de la edición y horarios
(0024829, 0024822, 0024802, 0024794)."""

from tests.conftest import future_weekday, slot

BASE = {"full_name": "Pedro Navaja", "description": "Clásicos", "photo_url": "https://i.pravatar.cc/320?img=8",
        "rating": "4.5", "is_available": True, "is_active": True, "service_ids": [1, 2]}


def test_create_barber_and_exact_rating(admin, anon):
    r = admin.post("/api/barbers", BASE)
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    pub = next(b for b in anon.get("/api/barbers").json() if b["id"] == bid)
    assert pub["rating"] == "4.5"  # 0024822: no se redondea a 5


def test_barber_validations_extreme_data(admin):
    """0024829: nombre con números/símbolos, rating fuera de rango o con 2 decimales, URL inválida o enorme."""
    r = admin.post("/api/barbers", {**BASE, "full_name": "Pedro 1234567890$$$", "rating": "5.5", "photo_url": "javascript:alert(1)"})
    fields = r.json()["error"]["fields"]
    assert r.status_code == 422 and {"full_name", "rating", "photo_url"} <= set(fields)
    assert admin.post("/api/barbers", {**BASE, "rating": "4.55"}).status_code == 422
    assert admin.post("/api/barbers", {**BASE, "full_name": "A" * 200}).status_code == 422
    assert admin.post("/api/barbers", {**BASE, "photo_url": "https://x.com/" + "a" * 600}).status_code == 422
    assert admin.post("/api/barbers", {**BASE, "service_ids": []}).status_code == 422
    assert admin.post("/api/barbers", {**BASE, "service_ids": [999]}).status_code == 400


def test_edit_barber_persists_and_reflects_publicly(admin, anon):
    """0024802 / 0024794: disponibilidad, puntuación y servicios se guardan de verdad."""
    r = admin.put("/api/barbers/2", {**BASE, "full_name": "Marco Style", "rating": "4.7", "is_available": False, "service_ids": [1, 4]})
    assert r.status_code == 200
    body = r.json()
    assert body["rating"] == "4.7" and body["is_available"] is False and [s["id"] for s in body["services"]] == [1, 4]
    again = admin.get("/api/barbers/2").json()
    assert again["rating"] == "4.7" and again["is_available"] is False
    pub = next(b for b in anon.get("/api/barbers").json() if b["id"] == 2)
    assert pub["rating"] == "4.7" and pub["is_available"] is False and {s["name"] for s in pub["services"]} == {"Corte", "Cejas"}
    actions = [a["action"] for a in admin.get("/api/audit", params={"entity": "barber"}).json()["items"]]
    assert "BARBERO_EDITADO" in actions


def test_barber_name_change_syncs_user(admin):
    admin.put("/api/barbers/1", {**BASE, "full_name": "Diego Castillo", "service_ids": [1, 2, 3, 4]})
    assert admin.get("/api/users/3").json()["full_name"] == "Diego Castillo"


def test_cannot_deactivate_barber_with_future_appointments(admin):
    r = admin.put("/api/barbers/1", {**BASE, "full_name": "Diego C", "is_active": False, "service_ids": [1, 2, 3, 4]})
    assert r.status_code == 409


def test_inactive_barber_hidden_from_public(admin, anon):
    admin.put("/api/barbers/3", {**BASE, "full_name": "Luis Fade", "is_active": False, "service_ids": [1, 4]})
    assert 3 not in [b["id"] for b in anon.get("/api/barbers").json()]


def test_schedule_validation_and_effect(admin, anon):
    bad = admin.put("/api/barbers/2/schedule", {"days": [{"weekday": 0, "start_time": "10:00", "end_time": "09:00"}]})
    assert bad.status_code == 422
    bad_break = admin.put("/api/barbers/2/schedule", {"days": [{"weekday": 0, "start_time": "10:00", "end_time": "18:00", "break_start": "19:00", "break_end": "20:00"}]})
    assert bad_break.status_code == 422
    ok = admin.put("/api/barbers/2/schedule", {"days": [{"weekday": 0, "start_time": "10:00", "end_time": "12:00"}]})
    assert ok.status_code == 200 and len(ok.json()) == 1
    tuesday = future_weekday(1)
    av = anon.get("/api/availability", params={"barber_id": 2, "service_id": 1, "date": tuesday.isoformat()}).json()
    assert av["working"] is False  # día no laborable
    monday = future_weekday(0)
    av = anon.get("/api/availability", params={"barber_id": 2, "service_id": 1, "date": monday.isoformat()}).json()
    assert [s["time"] for s in av["slots"]] == ["10:00", "10:30", "11:00"]  # 45 min deben caber antes de las 12:00


def test_time_off_blocks_and_conflicts(admin, barbero, cliente):
    day = future_weekday(2)
    r = barbero.post("/api/barbers/1/time-off", {"start_at": f"{day}T09:00", "end_at": f"{day}T12:00", "reason": "Capacitación"})
    assert r.status_code == 201
    av = cliente.get("/api/availability", params={"barber_id": 1, "service_id": 2, "date": day.isoformat()}).json()
    blocked = {s["time"] for s in av["slots"] if s["reason"] == "bloqueado"}
    assert "09:00" in blocked and "11:30" in blocked and "12:00" not in blocked
    assert cliente.post("/api/appointments", {"service_id": 2, "barber_id": 1, "start_at": slot(day, "10:00")}).status_code == 400
    # Un bloqueo sobre una cita existente se rechaza.
    assert cliente.post("/api/appointments", {"service_id": 2, "barber_id": 1, "start_at": slot(day, "15:00")}).status_code == 201
    conflict = admin.post("/api/barbers/1/time-off", {"start_at": f"{day}T14:00", "end_at": f"{day}T16:00"})
    assert conflict.status_code == 409
    # Un barbero no puede bloquear la agenda de otro.
    assert barbero.post("/api/barbers/2/time-off", {"start_at": f"{day}T09:00", "end_at": f"{day}T10:00"}).status_code == 403
