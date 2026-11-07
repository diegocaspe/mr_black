"""Carrito, ventas (online, mostrador y cobro de servicios), pagos y comprobantes."""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import BackgroundTasks
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.deps import RequestMeta, active_user_ids_with_roles
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.core.timeutils import day_bounds_utc
from app.integrations.email import Attachment, OutgoingEmail, render_layout
from app.models.appointment import ATENDIDA, Appointment
from app.models.cart import Cart, CartItem
from app.models.client import Client
from app.models.product import MOVEMENT_DEVOLUCION, MOVEMENT_VENTA, Product
from app.models.sale import (
    CHANNEL_MOSTRADOR,
    CHANNEL_ONLINE,
    PAYMENT_ANULADO,
    PAYMENT_APROBADO,
    PAYMENT_PENDIENTE,
    SALE_ANULADA,
    SALE_PAGADA,
    SALE_PENDIENTE_PAGO,
    Payment,
    PaymentMethod,
    Receipt,
    Sale,
    SaleItem,
)
from app.models.user import ROLE_ADMIN, ROLE_CAJA, ROLE_CLIENTE, User
from app.schemas.sale import CartLineOut, CartOut, PaymentDetailsIn, SaleOut
from app.services import payment_service
from app.services.audit_service import audit
from app.services.notification_service import notify, notify_many, send_email_task
from app.services.product_service import apply_stock_change

logger = logging.getLogger("mrblack.sales")
CENT = Decimal("0.01")


def insufficient(p: Product) -> str:
    return f"Stock insuficiente: quedan {p.stock} unidades." if p.stock > 0 else f"{p.name} está agotado."


# ------------------------------------------------------------------ carrito


def _get_cart(db: Session, client: Client, create: bool = True) -> Cart | None:
    cart = db.scalars(select(Cart).where(Cart.client_id == client.id)).first()
    if not cart and create:
        cart = Cart(client_id=client.id)
        db.add(cart)
        db.flush()
    return cart


def cart_view(db: Session, client: Client) -> CartOut:
    cart = _get_cart(db, client, create=False)
    lines: list[CartLineOut] = []
    issues: list[str] = []
    subtotal = Decimal("0.00")
    count = 0
    for item in (cart.items if cart else []):
        p = item.product
        issue = None
        if not p.is_active:
            issue = "Este producto ya no está disponible."
        elif p.stock < item.quantity:
            issue = insufficient(p)
        line_total = (p.price * item.quantity).quantize(CENT)
        if issue:
            issues.append(f"{p.name}: {issue}")
        else:
            subtotal += line_total
        count += item.quantity
        lines.append(CartLineOut(product_id=p.id, name=p.name, icon=p.icon, image_url=p.cover_url, unit_price=p.price,
                                 quantity=item.quantity, line_total=line_total, stock=p.stock,
                                 available=issue is None, issue=issue))
    return CartOut(items=lines, item_count=count, subtotal=subtotal, total=subtotal,
                   can_checkout=bool(lines) and not issues and subtotal > 0, issues=issues)


def _validate_qty(p: Product, qty: int) -> None:
    if not p.is_active:
        raise Conflict("Este producto ya no está disponible.", code="product_inactive")
    if p.price <= 0:
        raise Conflict("Este producto no tiene un precio válido.", code="invalid_price")
    if qty > p.stock:
        raise Conflict(insufficient(p), code="insufficient_stock", fields={"quantity": f"Máximo {p.stock} unidades."})


def add_to_cart(db: Session, client: Client, product_id: int, qty: int) -> CartOut:
    p = db.get(Product, product_id)
    if not p or not p.is_active:
        raise NotFound("El producto no existe o no está disponible.")
    cart = _get_cart(db, client)
    item = db.get(CartItem, (cart.id, p.id))
    new_qty = (item.quantity if item else 0) + qty
    if new_qty > p.stock:
        already = item.quantity if item else 0
        msg = insufficient(p) + (f" Ya tienes {already} en tu carrito." if already else "")
        raise Conflict(msg, code="insufficient_stock", fields={"quantity": f"Máximo {p.stock} unidades."})
    _validate_qty(p, new_qty)
    if item:
        item.quantity = new_qty
    else:
        db.add(CartItem(cart_id=cart.id, product_id=p.id, quantity=new_qty))
    db.commit()
    db.expire_all()
    return cart_view(db, client)


def set_cart_quantity(db: Session, client: Client, product_id: int, qty: int) -> CartOut:
    cart = _get_cart(db, client)
    item = db.get(CartItem, (cart.id, product_id))
    if not item:
        raise NotFound("El producto no está en tu carrito.")
    _validate_qty(item.product, qty)
    item.quantity = qty
    db.commit()
    db.expire_all()
    return cart_view(db, client)


def remove_from_cart(db: Session, client: Client, product_id: int) -> CartOut:
    cart = _get_cart(db, client)
    item = db.get(CartItem, (cart.id, product_id))
    if item:
        db.delete(item)
        db.commit()
    db.expire_all()
    return cart_view(db, client)


def clear_cart(db: Session, client: Client) -> CartOut:
    cart = _get_cart(db, client, create=False)
    if cart:
        for item in list(cart.items):
            db.delete(item)
        db.commit()
    db.expire_all()
    return cart_view(db, client)


# ------------------------------------------------------------------ ventas


def _method(db: Session, code: str, channel: str) -> PaymentMethod:
    m = db.get(PaymentMethod, code)
    if not m or not m.is_active:
        raise BadRequest("Método de pago no disponible.", fields={"payment_method": "Método inválido."})
    if channel == CHANNEL_ONLINE and not m.online_allowed:
        raise BadRequest(f"{m.name} no está disponible para compras en línea.", fields={"payment_method": "No disponible en línea."})
    if channel == CHANNEL_MOSTRADOR and not m.counter_allowed:
        raise BadRequest(f"{m.name} no está disponible en caja.", fields={"payment_method": "No disponible en caja."})
    return m


def _lock_products(db: Session, quantities: dict[int, int]) -> dict[int, Product]:
    """Bloquea las filas en orden de id (evita interbloqueos) y revalida estado y stock."""
    products = {
        p.id: p
        for p in db.scalars(
            select(Product).where(Product.id.in_(quantities)).order_by(Product.id).with_for_update(of=Product)
            # populate_existing: refresca objetos ya cargados (p. ej. vía el carrito) con el stock bloqueado actual.
            .execution_options(populate_existing=True)
        ).unique().all()
    }
    errors = []
    for pid, qty in quantities.items():
        p = products.get(pid)
        if not p or not p.is_active:
            errors.append(f"{p.name if p else 'Un producto'} ya no está disponible.")
        elif p.stock < qty:
            errors.append(f"{p.name}: {insufficient(p)}")
    if errors:
        raise Conflict(" ".join(errors), code="insufficient_stock")
    return products


def _next_receipt_number(db: Session) -> int:
    return db.execute(text("SELECT nextval('receipt_number_seq')")).scalar_one()


def _create_sale(
    db: Session,
    *,
    client: Client | None,
    channel: str,
    method: PaymentMethod,
    lines: list[dict],
    details: PaymentDetailsIn,
    actor: User,
    notes: str | None = None,
) -> tuple[Sale, payment_service.PaymentResult]:
    subtotal = sum((ln["unit_price"] * ln["quantity"] for ln in lines), Decimal("0.00")).quantize(CENT)
    if subtotal <= 0:
        # 0022634: nunca se registra una venta con total S/ 0.00.
        raise BadRequest("El total de la compra debe ser mayor a S/ 0.00.", code="zero_total")
    result = payment_service.process(method.code, subtotal, details)  # puede lanzar 402 (rechazo)

    now = datetime.now(UTC)
    sale = Sale(
        client_id=client.id if client else None,
        channel=channel,
        status=SALE_PAGADA if result.approved else SALE_PENDIENTE_PAGO,
        payment_method=method.code,
        subtotal=subtotal,
        discount=Decimal("0.00"),
        total=subtotal,
        notes=notes,
        created_by=actor.id,
        paid_at=now if result.approved else None,
    )
    db.add(sale)
    db.flush()
    for ln in lines:
        db.add(SaleItem(sale_id=sale.id, product_id=ln.get("product_id"), service_id=ln.get("service_id"),
                        appointment_id=ln.get("appointment_id"), description=ln["description"][:120],
                        quantity=ln["quantity"], unit_price=ln["unit_price"],
                        line_total=(ln["unit_price"] * ln["quantity"]).quantize(CENT)))
        if ln.get("product"):
            apply_stock_change(db, ln["product"], -ln["quantity"], MOVEMENT_VENTA, actor.id, f"Venta #{sale.id}", sale.id)
    db.add(Payment(sale_id=sale.id, method_code=method.code, amount=subtotal,
                   status=PAYMENT_APROBADO if result.approved else PAYMENT_PENDIENTE,
                   reference=result.reference, payer_detail=result.payer_detail,
                   processed_by=actor.id if result.approved else None, processed_at=now if result.approved else None))
    db.add(Receipt(sale_id=sale.id, series="B001", number=_next_receipt_number(db),
                   customer_name=client.full_name if client else "Cliente varios",
                   customer_phone=client.phone if client else None))
    db.flush()
    return sale, result


def checkout(db: Session, user: User, method_code: str, details: PaymentDetailsIn, meta: RequestMeta,
             tasks: BackgroundTasks) -> SaleOut:
    client = user.client
    cart = _get_cart(db, client, create=False)
    if not cart or not cart.items:
        raise BadRequest("Tu carrito está vacío.", code="empty_cart")
    method = _method(db, method_code, CHANNEL_ONLINE)
    quantities = {i.product_id: i.quantity for i in cart.items}
    products = _lock_products(db, quantities)  # revalidación final en el servidor
    lines = [
        {"product": products[pid], "product_id": pid, "description": products[pid].name,
         "quantity": qty, "unit_price": products[pid].price}
        for pid, qty in quantities.items()
    ]
    sale, result = _create_sale(db, client=client, channel=CHANNEL_ONLINE, method=method, lines=lines,
                                details=details, actor=user)
    for item in list(cart.items):
        db.delete(item)
    audit(db, user.id, "VENTA_ONLINE", "sale", sale.id,
          {"total": str(sale.total), "metodo": method.code, "estado": sale.status}, meta)
    if sale.status == SALE_PAGADA:
        notify(db, user.id, "PAGO_PROCESADO", "Pago procesado",
               f"Tu compra por S/ {sale.total:.2f} fue pagada con {method.name}.", f"#/compras/{sale.id}")
    else:
        notify(db, user.id, "COMPRA_REALIZADA", "Pedido registrado",
               f"Tu pedido por S/ {sale.total:.2f} está reservado. Paga al recogerlo en el local.", f"#/compras/{sale.id}")
        notify_many(db, active_user_ids_with_roles(db, (ROLE_CAJA,)), "PEDIDO_PENDIENTE", "Pedido por cobrar en local",
                    f"{client.full_name} reservó productos por S/ {sale.total:.2f}.", f"#/ventas/{sale.id}")
    db.commit()
    out = sale_out(db, sale.id, result.change_due)
    _queue_receipt_email(tasks, sale.id)
    return out


def counter_sale(db: Session, data, actor: User, meta: RequestMeta, tasks: BackgroundTasks) -> SaleOut:
    client = None
    if data.client_id:
        client = db.get(Client, data.client_id)
        if not client:
            raise NotFound("El cliente no existe.")
    method = _method(db, data.payment_method, CHANNEL_MOSTRADOR)
    quantities = {i.product_id: i.quantity for i in data.items}
    products = _lock_products(db, quantities)
    lines = [
        {"product": products[pid], "product_id": pid, "description": products[pid].name,
         "quantity": qty, "unit_price": products[pid].price}
        for pid, qty in quantities.items()
    ]
    sale, result = _create_sale(db, client=client, channel=CHANNEL_MOSTRADOR, method=method, lines=lines,
                                details=data.payment, actor=actor, notes=data.notes)
    audit(db, actor.id, "VENTA_MOSTRADOR", "sale", sale.id, {"total": str(sale.total), "metodo": method.code}, meta)
    if client and client.user_id:
        notify(db, client.user_id, "COMPRA_REALIZADA", "Compra registrada",
               f"Registramos tu compra por S/ {sale.total:.2f}.", f"#/compras/{sale.id}")
    db.commit()
    out = sale_out(db, sale.id, result.change_due)
    _queue_receipt_email(tasks, sale.id)
    return out


def charge_appointment(db: Session, appointment_id: int, method_code: str, details: PaymentDetailsIn, actor: User,
                       meta: RequestMeta, tasks: BackgroundTasks, items=()) -> SaleOut:
    """Cobra el servicio y, opcionalmente, productos extra: una sola venta, un pago y un comprobante."""
    a = db.scalars(
        select(Appointment).where(Appointment.id == appointment_id).with_for_update(of=Appointment)
        .execution_options(populate_existing=True)
    ).unique().first()
    if not a:
        raise NotFound("La cita no existe.")
    if a.status != ATENDIDA:
        raise Conflict("Solo se pueden cobrar citas atendidas.", code="not_attended")
    if a.sale_id:
        raise Conflict("Esta cita ya fue cobrada.", code="already_charged")
    method = _method(db, method_code, CHANNEL_MOSTRADOR)
    lines = [{"service_id": a.service_id, "appointment_id": a.id,
              "description": f"{a.service.name} · {a.barber.full_name}", "quantity": 1, "unit_price": a.price}]
    quantities = {i.product_id: i.quantity for i in items}
    if quantities:
        products = _lock_products(db, quantities)  # activos y con stock; si no, no se registra nada
        lines += [
            {"product": products[pid], "product_id": pid, "description": products[pid].name,
             "quantity": qty, "unit_price": products[pid].price}
            for pid, qty in quantities.items()
        ]
    sale, result = _create_sale(db, client=a.client, channel=CHANNEL_MOSTRADOR, method=method, lines=lines,
                                details=details, actor=actor)
    a.sale_id = sale.id
    audit(db, actor.id, "CITA_COBRADA", "appointment", a.id,
          {"venta": sale.id, "total": str(sale.total), "metodo": method.code, "productos": len(quantities)}, meta)
    if a.client.user_id:
        extra = f" + {len(quantities)} producto(s)" if quantities else ""
        notify(db, a.client.user_id, "PAGO_PROCESADO", "Pago de servicio registrado",
               f"{a.service.name}{extra}: S/ {sale.total:.2f} pagado con {method.name}.", f"#/compras/{sale.id}")
    db.commit()
    out = sale_out(db, sale.id, result.change_due)
    _queue_receipt_email(tasks, sale.id)
    return out


def _lock_sale(db: Session, sale_id: int) -> Sale:
    sale = db.scalars(
        select(Sale).where(Sale.id == sale_id).with_for_update(of=Sale).execution_options(populate_existing=True)
    ).unique().first()
    if not sale:
        raise NotFound("La venta no existe.")
    return sale


def confirm_payment(db: Session, sale_id: int, method_code: str, details: PaymentDetailsIn, actor: User,
                    meta: RequestMeta, tasks: BackgroundTasks) -> SaleOut:
    """Cobro en el local de un pedido online reservado con 'Pago en local'."""
    sale = _lock_sale(db, sale_id)
    if sale.status != SALE_PENDIENTE_PAGO:
        raise Conflict("Esta venta no tiene un pago pendiente.", code="not_pending")
    method = _method(db, method_code, CHANNEL_MOSTRADOR)
    result = payment_service.process(method.code, sale.total, details)
    now = datetime.now(UTC)
    for p in sale.payments:
        if p.status == PAYMENT_PENDIENTE:
            p.status = PAYMENT_ANULADO
    db.add(Payment(sale_id=sale.id, method_code=method.code, amount=sale.total, status=PAYMENT_APROBADO,
                   reference=result.reference, payer_detail=result.payer_detail, processed_by=actor.id, processed_at=now))
    sale.status = SALE_PAGADA
    sale.paid_at = now
    audit(db, actor.id, "PAGO_CONFIRMADO", "sale", sale.id, {"metodo": method.code, "total": str(sale.total)}, meta)
    if sale.client and sale.client.user_id:
        notify(db, sale.client.user_id, "PAGO_PROCESADO", "Pago recibido",
               f"Recibimos el pago de tu pedido por S/ {sale.total:.2f}. ¡Gracias!", f"#/compras/{sale.id}")
    db.commit()
    out = sale_out(db, sale.id, result.change_due)
    _queue_receipt_email(tasks, sale.id)
    return out


def cancel_sale(db: Session, sale_id: int, reason: str | None, actor: User, meta: RequestMeta) -> SaleOut:
    """Anula un pedido pendiente de pago y devuelve el stock reservado."""
    sale = _lock_sale(db, sale_id)
    if actor.role_code == ROLE_CLIENTE and (not actor.client or sale.client_id != actor.client.id):
        raise NotFound("La venta no existe.")
    if sale.status != SALE_PENDIENTE_PAGO:
        raise Conflict("Solo se pueden anular pedidos pendientes de pago.", code="not_pending")
    for item in sale.items:
        if item.product_id:
            p = db.scalars(
                select(Product).where(Product.id == item.product_id).with_for_update(of=Product)
                .execution_options(populate_existing=True)
            ).unique().one()
            apply_stock_change(db, p, item.quantity, MOVEMENT_DEVOLUCION, actor.id, f"Anulación venta #{sale.id}", sale.id)
    for p in sale.payments:
        if p.status == PAYMENT_PENDIENTE:
            p.status = PAYMENT_ANULADO
    sale.status = SALE_ANULADA
    sale.cancelled_at = datetime.now(UTC)
    sale.cancel_reason = reason
    audit(db, actor.id, "VENTA_ANULADA", "sale", sale.id, {"motivo": reason}, meta)
    if sale.client and sale.client.user_id and sale.client.user_id != actor.id:
        notify(db, sale.client.user_id, "PEDIDO_ANULADO", "Pedido anulado",
               f"Tu pedido #{sale.id} fue anulado." + (f" Motivo: {reason}" if reason else ""), f"#/compras/{sale.id}")
    db.commit()
    return sale_out(db, sale.id)


# ------------------------------------------------------------------ consultas


def sale_out(db: Session, sale_id: int, change_due: Decimal | None = None) -> SaleOut:
    db.expire_all()
    sale = db.get(Sale, sale_id)
    out = SaleOut.model_validate(sale)
    out.receipt_code = sale.receipt.code if sale.receipt else None
    out.payment_method_name = sale.method.name if sale.method else None
    out.created_by_name = sale.creator.full_name if sale.creator else None
    out.change_due = change_due
    return out


def get_sale_for_user(db: Session, sale_id: int, user: User) -> Sale:
    sale = db.get(Sale, sale_id)
    if not sale:
        raise NotFound("La venta no existe.")
    if user.role_code == ROLE_CLIENTE:
        if not user.client or sale.client_id != user.client.id:
            raise NotFound("La venta no existe.")
    elif user.role_code not in (ROLE_ADMIN, ROLE_CAJA):
        raise Forbidden()
    return sale


def list_sales(
    db: Session,
    user: User,
    *,
    status: str | None = None,
    channel: str | None = None,
    method: str | None = None,
    client_id: int | None = None,
    client_q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[SaleOut], int]:
    if date_from and date_to and date_from > date_to:
        raise BadRequest("La fecha inicial no puede ser posterior a la final.", fields={"date_from": "Rango invertido."})
    stmt = select(Sale).outerjoin(Client, Client.id == Sale.client_id)
    if user.role_code == ROLE_CLIENTE:
        if not user.client:
            return [], 0
        stmt = stmt.where(Sale.client_id == user.client.id)
    if status:
        stmt = stmt.where(Sale.status == status)
    if channel:
        stmt = stmt.where(Sale.channel == channel)
    if method:
        stmt = stmt.where(Sale.payment_method == method)
    if client_id:
        stmt = stmt.where(Sale.client_id == client_id)
    if client_q:
        like = f"%{client_q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Client.full_name).like(like), Client.phone.like(like)))
    if date_from:
        stmt = stmt.where(Sale.created_at >= day_bounds_utc(date_from)[0])
    if date_to:
        stmt = stmt.where(Sale.created_at < day_bounds_utc(date_to)[1])
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.order_by(Sale.created_at.desc(), Sale.id.desc()).offset((page - 1) * page_size).limit(page_size)).unique().all()
    outs = []
    for s in rows:
        o = SaleOut.model_validate(s)
        o.receipt_code = s.receipt.code if s.receipt else None
        o.payment_method_name = s.method.name if s.method else None
        o.created_by_name = s.creator.full_name if s.creator else None
        outs.append(o)
    return outs, total


def _queue_receipt_email(tasks: BackgroundTasks, sale_id: int) -> None:
    tasks.add_task(send_receipt_email_task, sale_id)


def send_receipt_email_task(sale_id: int) -> None:
    from app.integrations.pdf import render_receipt_pdf
    from app.services.settings_service import get_setting

    db = SessionLocal()
    try:
        sale = db.get(Sale, sale_id)
        if not sale or not sale.client:
            return
        to = sale.client.email or (sale.client.user.email if sale.client.user else None)
        if not to:
            return
        business = get_setting(db, "business")
        pdf = render_receipt_pdf(sale, business)
        status_text = {SALE_PAGADA: "Pagado", SALE_PENDIENTE_PAGO: "Pendiente de pago en local"}.get(sale.status, sale.status)
        rows = [(f"{i.description} × {i.quantity}", f"S/ {i.line_total:.2f}") for i in sale.items]
        rows += [("Total", f"S/ {sale.total:.2f}"), ("Método de pago", sale.method.name), ("Estado", status_text)]
        html, text_body = render_layout(
            "Gracias por tu compra",
            f"Hola {sale.client.full_name}, adjuntamos tu comprobante {sale.receipt.code}.",
            rows,
            ("Ver mis compras", f"{get_settings().frontend_url}/app.html#/compras/{sale.id}"),
        )
        email = OutgoingEmail(to, f"Comprobante {sale.receipt.code} · Mr Black", html, text_body, "comprobante",
                              [Attachment(f"comprobante-{sale.receipt.code}.pdf", pdf)])
    finally:
        db.close()
    send_email_task(email)
