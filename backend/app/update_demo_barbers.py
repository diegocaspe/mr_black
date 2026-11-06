"""Actualiza los barberos de demostración en una base que ya tiene datos (idempotente).

El seed solo se ejecuta en una base vacía. Este script lleva una base existente (p. ej. Railway)
al equipo actual de barberos sin tocar citas, ventas ni clientes:

  a) barbero1, barbero2 y barbero3: nombre, descripción, foto, valoración, disponibilidad,
     horario y servicios (se buscan por nombre de usuario);
  b) barbero4: se crea (usuario BARBERO + barbero + horario + servicios) si no existe.

Ejecutarlo varias veces deja siempre el mismo resultado. La base se toma de DATABASE_URL
(variable de entorno); el script no la guarda en ningún archivo:

    DATABASE_URL='postgresql://...' python -m app.update_demo_barbers

Contraseña de barbero4 (solo al crearlo): SEED_DEFAULT_PASSWORD si está definida; si no, la
misma que ya tiene barbero1 en esa base (la contraseña del seed); si tampoco existe, se genera
una y se muestra una sola vez.
"""

import logging
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Barber, BarberSchedule, Role, Service, User
from app.models.user import ROLE_BARBERO

log = logging.getLogger("update_demo_barbers")

# Lunes (0) a sábado (5), 09:00–19:30 con descanso 13:00–14:00.
WORKDAYS = range(0, 6)
START, END = time(9), time(19, 30)
BREAK_START, BREAK_END = time(13), time(14)

# Servicios por nombre (los del seed). Cada servicio queda con al menos 2 barberos:
# Corte 3 · Barba 3 · Corte + Barba 4 · Cejas 3.
DEMO_BARBERS = [
    {
        "username": "barbero1",
        "full_name": "Adriano Vargas",
        "rating": "4.9",
        "photo_url": "/assets/barberos/adriano-vargas.jpg",
        "description": "Especialista en fades y degradados con acabado a navaja. 9 años de experiencia.",
        "services": ["Corte", "Barba", "Corte + Barba", "Cejas"],
    },
    {
        "username": "barbero2",
        "full_name": "Alexander Huamán",
        "rating": "4.7",
        "photo_url": "/assets/barberos/alexander-huaman.jpg",
        "description": "Cortes clásicos y modernos a tijera, con lavado y peinado. 6 años de experiencia.",
        "services": ["Corte", "Barba", "Corte + Barba"],
    },
    {
        "username": "barbero3",
        "full_name": "Luis Quispe",
        "rating": "4.6",
        "photo_url": "/assets/barberos/luis-quispe.jpg",
        "description": "Diseños con navaja, líneas y perfilado de cejas de precisión. 5 años de experiencia.",
        "services": ["Corte", "Corte + Barba", "Cejas"],
    },
    {
        "username": "barbero4",
        "full_name": "Jhonatan Rojas",
        "rating": "4.5",
        "photo_url": "/assets/barberos/jhonatan-rojas.jpg",
        "description": "Arreglo y diseño de barba, afeitado clásico con toalla caliente. 4 años de experiencia.",
        "services": ["Barba", "Corte + Barba", "Cejas"],
    },
]


def apply_schedule(db: Session, barber: Barber) -> None:
    """Deja lun–sáb 09:00–19:30 (descanso 13–14) actualizando las filas existentes en su lugar
    (la restricción única barbero+día impide borrar e insertar en el mismo flush)."""
    by_day = {s.weekday: s for s in barber.schedules}
    for wd in WORKDAYS:
        s = by_day.pop(wd, None)
        if s is None:
            barber.schedules.append(BarberSchedule(weekday=wd, start_time=START, end_time=END,
                                                   break_start=BREAK_START, break_end=BREAK_END))
        else:
            s.start_time, s.end_time, s.break_start, s.break_end = START, END, BREAK_START, BREAK_END
    for s in by_day.values():  # domingo u otros días fuera del horario
        barber.schedules.remove(s)


def apply_profile(db: Session, barber: Barber, data: dict, services_by_name: dict[str, Service]) -> None:
    barber.full_name = data["full_name"]
    barber.description = data["description"]
    barber.photo_url = data["photo_url"]
    barber.rating = Decimal(data["rating"])
    barber.is_active = True
    barber.is_available = True
    if barber.user is not None:
        barber.user.full_name = data["full_name"]
    missing = [n for n in data["services"] if n not in services_by_name]
    if missing:
        log.warning("%s: no existen los servicios %s; se asignan los demás.", data["username"], ", ".join(missing))
    barber.services = [services_by_name[n] for n in data["services"] if n in services_by_name]
    apply_schedule(db, barber)


def _new_barber_password_hash(db: Session) -> str:
    from app.core.config import get_settings
    from app.core.security import hash_password

    if get_settings().seed_default_password:
        from app.seed import _password

        return hash_password(_password())
    ref = db.scalar(select(User).where(User.username == "barbero1"))
    if ref is not None:
        return ref.password_hash
    from app.seed import _password

    return hash_password(_password())  # genera una y la muestra en el log


def create_user_and_barber(db: Session, data: dict, services_by_name: dict[str, Service], pwd_hash: str) -> Barber:
    role_id = db.scalar(select(Role.id).where(Role.code == ROLE_BARBERO))
    user = db.scalar(select(User).where(User.username == data["username"]))
    if user is None:
        user = User(username=data["username"], full_name=data["full_name"], email=f"{data['username']}@example.com",
                    role_id=role_id, password_hash=pwd_hash, is_active=True, password_changed_at=datetime.now(UTC))
        db.add(user)
        db.flush()
    barber = Barber(user_id=user.id, full_name=data["full_name"], rating=Decimal(data["rating"]))
    db.add(barber)
    db.flush()
    return barber


def run(db: Session) -> list[str]:
    """Aplica los cambios en la sesión y hace commit. Devuelve un resumen por barbero."""
    services_by_name = {s.name: s for s in db.scalars(select(Service)).all()}
    summary = []
    for data in DEMO_BARBERS:
        user = db.scalar(select(User).where(User.username == data["username"]))
        barber = user.barber if user is not None else None
        if barber is None:
            if data["username"] != "barbero4":
                summary.append(f"{data['username']}: no existe en esta base; se omite.")
                continue
            barber = create_user_and_barber(db, data, services_by_name, _new_barber_password_hash(db))
            action = "creado"
        else:
            action = "actualizado"
        apply_profile(db, barber, data, services_by_name)
        db.flush()
        summary.append(f"{data['username']}: {action} → {data['full_name']} "
                       f"({', '.join(s.name for s in barber.services)})")
    db.commit()
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        for line in run(db):
            log.info(line)
        log.info("Barberos de demostración al día.")
    except Exception:
        db.rollback()
        log.exception("No se pudieron actualizar los barberos")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
