"""Datos iniciales de desarrollo (idempotente).

Migra los datos del prototipo `barberia0.3.html` (usuarios, barberos, clientes, servicios,
productos, citas y ventas) a PostgreSQL, con contraseñas hasheadas con Argon2.
La contraseña de los usuarios demo se toma de SEED_DEFAULT_PASSWORD (.env); si no está
definida se genera una aleatoria y se muestra una sola vez en el log.
"""

import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.timeutils import local_dt, today_local
from app.core.validators import validate_password
from app.models import (
    Appointment,
    AppointmentStatusHistory,
    Barber,
    BarberSchedule,
    Client,
    InventoryMovement,
    Payment,
    Product,
    ProductCategory,
    Receipt,
    Role,
    Sale,
    SaleItem,
    Service,
    User,
)

log = logging.getLogger("seed")


def _password() -> str:
    pwd = get_settings().seed_default_password
    if pwd:
        validate_password(pwd)
        return pwd
    pwd = "Mb-" + secrets.token_urlsafe(12) + "9a"
    log.warning("SEED_DEFAULT_PASSWORD no definido. Contraseña generada para usuarios demo: %s", pwd)
    return pwd


def run() -> None:
    if get_settings().is_production:
        # Los usuarios demo tienen una contraseña conocida: nunca deben existir en producción.
        raise RuntimeError("El seed de desarrollo no puede ejecutarse con ENVIRONMENT=production.")
    db = SessionLocal()
    try:
        if db.scalar(select(User.id).where(User.username == "admin")):
            log.info("Datos de desarrollo ya cargados; se omite el seed.")
            return
        log.info("Cargando datos de desarrollo…")
        pwd_hash = hash_password(_password())
        roles = {r.code: r.id for r in db.scalars(select(Role)).all()}
        now = datetime.now(UTC)

        def user(username, name, role, email, protected=False):
            u = User(username=username, full_name=name, email=email, role_id=roles[role], password_hash=pwd_hash,
                     is_active=True, is_protected=protected, password_changed_at=now)
            db.add(u)
            db.flush()
            return u

        admin = user("admin", "Administrador Principal", "ADMIN", "admin@example.com", protected=True)
        caja = user("caja", "Encargado de Caja", "CAJA", "caja@example.com")

        # ---------------- servicios (antes constante SERVICES del prototipo)
        services = {
            "corte": Service(name="Corte", description="Corte personalizado y acabado.", price=Decimal("35.00"),
                             duration_minutes=45, icon="fa-scissors"),
            "barba": Service(name="Barba", description="Perfilado y acabado de barba.", price=Decimal("25.00"),
                             duration_minutes=30, icon="fa-user-tie"),
            "combo": Service(name="Corte + Barba", description="La experiencia completa Mr Black.",
                             price=Decimal("55.00"), duration_minutes=70, icon="fa-star"),
            "cejas": Service(name="Cejas", description="Perfilado limpio y preciso.", price=Decimal("15.00"),
                             duration_minutes=15, icon="fa-eye"),
        }
        db.add_all(services.values())
        db.flush()

        # ---------------- barberos + horarios
        def barber(username, name, rating, available, photo, svc_keys, days, description):
            u = user(username, name, "BARBERO", f"{username}@example.com")
            b = Barber(user_id=u.id, full_name=name, rating=Decimal(rating), is_available=available,
                       photo_url=photo, description=description)
            b.services = [services[k] for k in svc_keys]
            db.add(b)
            db.flush()
            for wd in days:
                db.add(BarberSchedule(barber_id=b.id, weekday=wd, start_time=time(9), end_time=time(19, 30),
                                      break_start=time(13), break_end=time(14)))
            return b

        diego = barber("barbero1", "Diego C", "4.9", True, "https://i.pravatar.cc/320?img=12",
                       ["corte", "barba", "combo", "cejas"], range(0, 6),
                       "Especialista en fades y diseños clásicos. 8 años de experiencia.")
        marco = barber("barbero2", "Marco Style", "4.5", True, "https://i.pravatar.cc/320?img=33",
                       ["corte", "barba", "combo"], range(0, 6),
                       "Cortes modernos y perfilado de barba con navaja.")
        luis = barber("barbero3", "Luis Fade", "4.2", False, "https://i.pravatar.cc/320?img=52",
                      ["corte", "cejas"], range(1, 6), "Fades de alta precisión y perfilado de cejas.")

        # ---------------- clientes (con y sin cuenta)
        def client(name, phone, email, with_account=True, days_ago=0):
            u = None
            if with_account:
                u = user(phone, name, "CLIENTE", email)
            c = Client(user_id=u.id if u else None, full_name=name, phone=phone, email=email,
                       created_at=now - timedelta(days=days_ago))
            db.add(c)
            db.flush()
            return c

        carlos = client("Carlos Mendoza", "987654321", "carlos.mendoza@example.com", True, 25)
        andrea = client("Andrea Torres", "999888777", "andrea.torres@example.com", True, 18)
        jose = client("José Ramírez", "988111222", "jose.ramirez@example.com", False, 12)

        # ---------------- productos
        cats = {n: ProductCategory(name=n) for n in ("Cuidado del cabello", "Cuidado de barba", "Styling", "Accesorios")}
        db.add_all(cats.values())
        db.flush()
        product_rows = [
            ("Gel Mr Black", "Styling", "18.00", 12, 3, True, "Fijación y acabado natural.", "fa-bottle-droplet"),
            ("Shampoo Premium", "Cuidado del cabello", "28.00", 8, 3, True, "Limpieza suave para uso diario.", "fa-pump-soap"),
            ("Cera Matte", "Styling", "24.00", 2, 3, True, "Textura mate y fijación media.", "fa-box"),
            ("Aceite para Barba", "Cuidado de barba", "32.00", 0, 3, False, "Producto dado de baja temporalmente.", "fa-droplet"),
            ("Bálsamo para Barba", "Cuidado de barba", "30.00", 6, 4, True, "Suaviza y da forma a la barba.", "fa-jar"),
            ("Peine de Madera", "Accesorios", "15.00", 20, 5, True, "Peine artesanal antiestático.", "fa-grip-lines"),
        ]
        products = {}
        for name, cat, price, stock, min_stock, active, desc, icon in product_rows:
            p = Product(name=name, category_id=cats[cat].id, price=Decimal(price), stock=stock, min_stock=min_stock,
                        is_active=active, description=desc, icon=icon)
            db.add(p)
            db.flush()
            if stock:
                db.add(InventoryMovement(product_id=p.id, movement_type="ENTRADA", quantity=stock, stock_before=0,
                                         stock_after=stock, reason="Stock inicial (migración del prototipo)", user_id=admin.id))
            products[name] = p

        # ---------------- citas de ejemplo (fuera de la validación de disponibilidad: datos históricos)
        today = today_local()

        def appt(c, b, svc, day_offset, hh, mm, status, created_by):
            start = local_dt(today + timedelta(days=day_offset), time(hh, mm))
            s = services[svc]
            a = Appointment(client_id=c.id, barber_id=b.id, service_id=s.id, start_at=start,
                            end_at=start + timedelta(minutes=s.duration_minutes), status=status, price=s.price,
                            created_by=created_by)
            db.add(a)
            db.flush()
            db.add(AppointmentStatusHistory(appointment_id=a.id, from_status=None, to_status="PENDIENTE",
                                            note="Cita registrada", changed_by=created_by))
            if status in ("CONFIRMADA", "ATENDIDA"):
                db.add(AppointmentStatusHistory(appointment_id=a.id, from_status="PENDIENTE", to_status="CONFIRMADA",
                                                changed_by=caja.id))
            if status == "ATENDIDA":
                db.add(AppointmentStatusHistory(appointment_id=a.id, from_status="CONFIRMADA", to_status="ATENDIDA",
                                                changed_by=caja.id))
            if status == "CANCELADA":
                db.add(AppointmentStatusHistory(appointment_id=a.id, from_status="PENDIENTE", to_status="CANCELADA",
                                                note="Cancelada por el cliente", changed_by=created_by))
            return a

        a1 = appt(carlos, diego, "corte", -3, 10, 0, "ATENDIDA", carlos.user_id)
        appt(carlos, marco, "combo", 1, 16, 0, "CONFIRMADA", carlos.user_id)
        appt(andrea, diego, "barba", 2, 11, 30, "PENDIENTE", andrea.user_id)
        a4 = appt(jose, marco, "corte", -7, 15, 0, "ATENDIDA", caja.id)
        appt(andrea, luis, "cejas", -1, 17, 0, "CANCELADA", andrea.user_id)
        appt(jose, diego, "combo", -2, 9, 0, "ATENDIDA", caja.id)  # atendida y aún sin cobrar

        # ---------------- ventas históricas con pago y comprobante
        def sale(c, lines, method, days_ago, channel="MOSTRADOR", appointment=None):
            when = now - timedelta(days=days_ago)
            total = sum((Decimal(price) * qty for _, _, qty, price, _ in lines), Decimal("0.00"))
            s = Sale(client_id=c.id, channel=channel, status="PAGADA", payment_method=method, subtotal=total,
                     total=total, created_by=caja.id, created_at=when, paid_at=when)
            db.add(s)
            db.flush()
            for kind, ref, qty, price, desc in lines:
                db.add(SaleItem(sale_id=s.id, product_id=ref.id if kind == "p" else None,
                                service_id=ref.id if kind == "s" else None,
                                appointment_id=appointment.id if kind == "s" and appointment else None,
                                description=desc, quantity=qty, unit_price=Decimal(price),
                                line_total=Decimal(price) * qty))
            db.add(Payment(sale_id=s.id, method_code=method, amount=total, status="APROBADO",
                           reference=f"SEED-{s.id:05d}", payer_detail=method.title(), processed_by=caja.id,
                           created_at=when, processed_at=when))
            number = db.execute(text("SELECT nextval('receipt_number_seq')")).scalar_one()
            db.add(Receipt(sale_id=s.id, number=number, customer_name=c.full_name, customer_phone=c.phone, issued_at=when))
            if appointment:
                appointment.sale_id = s.id
            return s

        sale(carlos, [("p", products["Gel Mr Black"], 1, "18.00", "Gel Mr Black")], "EFECTIVO", 3)
        sale(andrea, [("p", products["Shampoo Premium"], 2, "28.00", "Shampoo Premium")], "ONLINE", 8, "ONLINE")
        sale(jose, [("p", products["Cera Matte"], 1, "24.00", "Cera Matte")], "YAPE", 2)
        sale(carlos, [("s", services["corte"], 1, "35.00", "Corte · Diego C")], "PLIN", 3, appointment=a1)
        sale(jose, [("s", services["corte"], 1, "35.00", "Corte · Marco Style")], "EFECTIVO", 7, appointment=a4)

        db.commit()
        log.info("Datos de desarrollo cargados correctamente.")
    except Exception:
        db.rollback()
        log.exception("Error cargando datos de desarrollo")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
