import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest
from app.core.timeutils import day_bounds_utc, today_local, tz
from app.core.validators import validate_report_date
from app.models.appointment import ACTIVE_STATUSES, ATENDIDA, CANCELADA, PENDIENTE, Appointment
from app.models.barber import Barber
from app.models.client import Client
from app.models.product import Product
from app.models.sale import PAYMENT_APROBADO, SALE_PAGADA, SALE_PENDIENTE_PAGO, Payment, PaymentMethod, Sale, SaleItem
from app.models.service import Service

ZERO = Decimal("0.00")


def validate_range(date_from: date, date_to: date) -> None:
    """0024831: fechas entre 2000-01-01 y 2099-12-31 y rango no invertido (también en el servidor)."""
    errors = {}
    for key, value in (("date_from", date_from), ("date_to", date_to)):
        try:
            validate_report_date(value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise BadRequest(next(iter(errors.values())), code="invalid_date", fields=errors)
    if date_from > date_to:
        raise BadRequest("La fecha 'Desde' no puede ser posterior a la fecha 'Hasta'.", code="invalid_range",
                         fields={"date_from": "Debe ser anterior o igual a 'Hasta'."})


def _local_day(col):
    return cast(func.timezone(str(tz()), col), Date)


def _income(db: Session, start: datetime, end: datetime) -> dict:
    rows = db.execute(
        select(
            func.coalesce(func.sum(SaleItem.line_total).filter(SaleItem.service_id.is_not(None)), 0),
            func.coalesce(func.sum(SaleItem.line_total).filter(SaleItem.product_id.is_not(None)), 0),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.status == SALE_PAGADA, Sale.paid_at >= start, Sale.paid_at < end)
    ).one()
    services, products = Decimal(rows[0]), Decimal(rows[1])
    count = db.scalar(select(func.count()).select_from(Sale).where(Sale.status == SALE_PAGADA, Sale.paid_at >= start, Sale.paid_at < end))
    return {"services": services, "products": products, "total": services + products, "sales_count": count}


def _by_method(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        select(PaymentMethod.code, PaymentMethod.name, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
        .join(Payment, (Payment.method_code == PaymentMethod.code) & (Payment.status == PAYMENT_APROBADO)
              & (Payment.processed_at >= start) & (Payment.processed_at < end), isouter=True)
        .group_by(PaymentMethod.code, PaymentMethod.name, PaymentMethod.sort_order)
        .order_by(PaymentMethod.sort_order)
    ).all()
    return [{"code": r[0], "name": r[1], "count": r[2], "amount": Decimal(r[3])} for r in rows]


def _daily(db: Session, d_from: date, d_to: date) -> list[dict]:
    start, end = day_bounds_utc(d_from)[0], day_bounds_utc(d_to)[1]
    day = _local_day(Sale.paid_at)
    rows = dict(
        db.execute(
            select(day, func.sum(Sale.total)).where(Sale.status == SALE_PAGADA, Sale.paid_at >= start, Sale.paid_at < end).group_by(day)
        ).all()
    )
    out = []
    span = (d_to - d_from).days
    for i in range(span + 1):
        d = d_from + timedelta(days=i)
        out.append({"date": d, "amount": Decimal(rows.get(d, 0) or 0)})
    return out


def _top_services(db: Session, start: datetime, end: datetime, limit: int = 5) -> list[dict]:
    rows = db.execute(
        select(Service.name, func.count(Appointment.id))
        .join(Appointment, Appointment.service_id == Service.id)
        .where(Appointment.start_at >= start, Appointment.start_at < end, Appointment.status != CANCELADA)
        .group_by(Service.name)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit)
    ).all()
    return [{"name": r[0], "count": r[1]} for r in rows]


def _top_barbers(db: Session, start: datetime, end: datetime, limit: int = 5) -> list[dict]:
    rows = db.execute(
        select(Barber.full_name, func.count(Appointment.id), func.count(Appointment.id).filter(Appointment.status == ATENDIDA))
        .join(Appointment, Appointment.barber_id == Barber.id)
        .where(Appointment.start_at >= start, Appointment.start_at < end, Appointment.status != CANCELADA)
        .group_by(Barber.full_name)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit)
    ).all()
    return [{"name": r[0], "count": r[1], "attended": r[2]} for r in rows]


def _top_products(db: Session, start: datetime, end: datetime, limit: int = 5) -> list[dict]:
    rows = db.execute(
        select(SaleItem.description, func.sum(SaleItem.quantity), func.sum(SaleItem.line_total))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(SaleItem.product_id.is_not(None), Sale.status == SALE_PAGADA, Sale.paid_at >= start, Sale.paid_at < end)
        .group_by(SaleItem.description)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(limit)
    ).all()
    return [{"name": r[0], "quantity": int(r[1]), "amount": Decimal(r[2])} for r in rows]


def _appointment_counts(db: Session, start: datetime, end: datetime) -> dict:
    rows = dict(
        db.execute(
            select(Appointment.status, func.count()).where(Appointment.start_at >= start, Appointment.start_at < end).group_by(Appointment.status)
        ).all()
    )
    return {s: rows.get(s, 0) for s in ("PENDIENTE", "CONFIRMADA", "ATENDIDA", "CANCELADA")} | {"total": sum(rows.values())}


def dashboard(db: Session) -> dict:
    today = today_local()
    t_start, t_end = day_bounds_utc(today)
    m_start = day_bounds_utc(today.replace(day=1))[0]
    last30 = datetime.now(UTC) - timedelta(days=30)
    now = datetime.now(UTC)

    low_stock = db.scalars(
        select(Product).where(Product.is_active.is_(True), Product.stock <= Product.min_stock).order_by(Product.stock, Product.name)
    ).unique().all()
    upcoming = db.scalars(
        select(Appointment).where(Appointment.start_at >= now, Appointment.status.in_(ACTIVE_STATUSES))
        .order_by(Appointment.start_at).limit(8)
    ).unique().all()
    return {
        "today": today,
        "sales_today": _income(db, t_start, t_end),
        "sales_month": _income(db, m_start, t_end),
        "appointments_today": _appointment_counts(db, t_start, t_end),
        "pending_appointments": db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.status == PENDIENTE, Appointment.start_at >= now)
        ),
        "pending_orders": db.scalar(select(func.count()).select_from(Sale).where(Sale.status == SALE_PENDIENTE_PAGO)),
        "unpaid_services": db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.status == ATENDIDA, Appointment.sale_id.is_(None))
        ),
        "clients": db.scalar(select(func.count()).select_from(Client)),
        "new_clients_month": db.scalar(select(func.count()).select_from(Client).where(Client.created_at >= m_start)),
        "active_products": db.scalar(select(func.count()).select_from(Product).where(Product.is_active.is_(True))),
        "low_stock": [
            {"id": p.id, "name": p.name, "stock": p.stock, "min_stock": p.min_stock, "status": p.stock_status} for p in low_stock
        ],
        "top_services": _top_services(db, last30, now + timedelta(days=365)),
        "top_barbers": _top_barbers(db, last30, now + timedelta(days=365)),
        "payment_methods_month": _by_method(db, m_start, t_end),
        "income_last_14_days": _daily(db, today - timedelta(days=13), today),
        "upcoming": [
            {
                "id": a.id, "start_at": a.start_at, "status": a.status, "client": a.client.full_name,
                "barber": a.barber.full_name, "service": a.service.name,
            }
            for a in upcoming
        ],
    }


def finance(db: Session, date_from: date, date_to: date) -> dict:
    validate_range(date_from, date_to)
    start, end = day_bounds_utc(date_from)[0], day_bounds_utc(date_to)[1]
    income = _income(db, start, end)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "income": income,
        "average_ticket": (income["total"] / income["sales_count"]).quantize(Decimal("0.01")) if income["sales_count"] else ZERO,
        "appointments": _appointment_counts(db, start, end),
        "by_method": _by_method(db, start, end),
        "daily": _daily(db, date_from, date_to) if (date_to - date_from).days <= 366 else [],
        "top_services": _top_services(db, start, end),
        "top_barbers": _top_barbers(db, start, end),
        "top_products": _top_products(db, start, end),
        "pending_orders_amount": Decimal(
            db.scalar(select(func.coalesce(func.sum(Sale.total), 0)).where(Sale.status == SALE_PENDIENTE_PAGO,
                                                                        Sale.created_at >= start, Sale.created_at < end))
        ),
    }


def sales_csv(db: Session, date_from: date, date_to: date) -> str:
    validate_range(date_from, date_to)
    start, end = day_bounds_utc(date_from)[0], day_bounds_utc(date_to)[1]
    sales = db.scalars(select(Sale).where(Sale.created_at >= start, Sale.created_at < end).order_by(Sale.created_at)).unique().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["venta", "comprobante", "fecha", "cliente", "canal", "metodo", "estado", "detalle", "total"])
    for s in sales:
        detail = "; ".join(f"{i.description} x{i.quantity}" for i in s.items)
        client_name = s.client.full_name if s.client else "Cliente varios"
        # Neutraliza fórmulas al abrir el CSV en Excel (CSV injection).
        safe = [v if not str(v).startswith(("=", "+", "-", "@")) else f"'{v}" for v in (client_name, detail)]
        w.writerow([s.id, s.receipt.code if s.receipt else "", s.created_at.astimezone(tz()).strftime("%Y-%m-%d %H:%M"),
                    safe[0], s.channel, s.payment_method, s.status, safe[1], f"{s.total:.2f}"])
    return "﻿" + buf.getvalue()
