"""Script update_demo_barbers: lleva una base con datos antiguos al equipo actual sin tocar
citas ni ventas, crea barbero4 si falta y es idempotente."""

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.update_demo_barbers import DEMO_BARBERS, run
from tests.conftest import PASSWORD, Api


def _snapshot():
    with engine.connect() as conn:
        return {
            "citas": conn.execute(text("SELECT id, barber_id, start_at, status FROM appointments ORDER BY id")).all(),
            "ventas": conn.execute(text("SELECT id, total FROM sales ORDER BY id")).all(),
            "items": conn.execute(text("SELECT id, description FROM sale_items ORDER BY id")).all(),
        }


def _old_database():
    """Simula la base desplegada antes del cambio: 3 barberos con los datos anteriores."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE barbers SET full_name='Luis Fade', is_available=false, rating=4.2, "
                          "photo_url='https://i.pravatar.cc/320?img=52' WHERE id=3"))
        conn.execute(text("UPDATE users SET full_name='Luis Fade' WHERE username='barbero3'"))
        conn.execute(text("DELETE FROM barber_schedules WHERE barber_id=3 AND weekday=0"))
        conn.execute(text("INSERT INTO barber_schedules (barber_id, weekday, start_time, end_time) VALUES (3, 6, '10:00', '12:00')"))
        conn.execute(text("UPDATE barber_schedules SET start_time='10:00', break_start=NULL, break_end=NULL WHERE barber_id=3 AND weekday=2"))
        conn.execute(text("DELETE FROM barber_services WHERE barber_id=3"))
        conn.execute(text("DELETE FROM barbers WHERE user_id=(SELECT id FROM users WHERE username='barbero4')"))
        conn.execute(text("DELETE FROM users WHERE username='barbero4'"))


def test_updates_existing_creates_barbero4_and_is_idempotent(anon):
    _old_database()
    before = _snapshot()

    with SessionLocal() as db:
        summary = run(db)
    assert any("barbero4: creado" in line for line in summary)
    with SessionLocal() as db:
        assert any("barbero4: actualizado" in line for line in run(db))  # segunda vez: sin duplicados

    assert _snapshot() == before  # citas y ventas intactas
    barbers = {b["full_name"]: b for b in anon.get("/api/barbers").json()}
    assert set(barbers) == {d["full_name"] for d in DEMO_BARBERS}
    for d in DEMO_BARBERS:
        b = barbers[d["full_name"]]
        assert b["photo_url"] == d["photo_url"] and b["rating"] == d["rating"] and b["is_available"] is True
        assert {s["name"] for s in b["services"]} == set(d["services"])

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT b.full_name, s.weekday, s.start_time::text, s.end_time::text, s.break_start::text, s.break_end::text "
            "FROM barber_schedules s JOIN barbers b ON b.id = s.barber_id ORDER BY 1, 2")).all()
        assert conn.execute(text("SELECT count(*) FROM users WHERE username='barbero4'")).scalar() == 1
        assert conn.execute(text("SELECT full_name FROM users WHERE username='barbero3'")).scalar() == "Luis Quispe"
    assert len(rows) == 4 * 6  # lunes a sábado para los 4
    assert {r[1:] for r in rows} == {(wd, "09:00:00", "19:30:00", "13:00:00", "14:00:00") for wd in range(6)}

    # barbero4 entra con la misma contraseña del seed y ve su agenda.
    assert Api().login("barbero4", PASSWORD).get("/api/appointments").status_code == 200


def test_every_service_has_at_least_two_barbers(anon):
    for service in anon.get("/api/services").json():
        names = [b["full_name"] for b in anon.get("/api/barbers").json()
                 if service["id"] in {s["id"] for s in b["services"]}]
        assert len(names) >= 2, (service["name"], names)


def test_demo_names_can_be_saved_from_the_panel():
    """El formulario de barberos valida el nombre: los del equipo demo deben pasar sin cambios."""
    from app.core.validators import validate_person_name

    for d in DEMO_BARBERS:
        assert validate_person_name(d["full_name"]) == d["full_name"]
