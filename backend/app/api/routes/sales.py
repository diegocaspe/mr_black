from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestMeta, client_of, get_current_user, get_request_meta, require_roles
from app.integrations.pdf import render_receipt_pdf
from app.models.sale import PaymentMethod
from app.models.user import ROLE_ADMIN, ROLE_CAJA, ROLE_CLIENTE, User
from app.schemas.common import Page
from app.schemas.sale import (
    CancelSaleIn,
    CartItemIn,
    CartOut,
    CartQtyIn,
    CheckoutIn,
    ConfirmPaymentIn,
    CounterSaleIn,
    PaymentMethodOut,
    SaleOut,
)
from app.services import sale_service
from app.services.settings_service import get_setting

router = APIRouter(prefix="/api", tags=["Carrito, ventas y pagos"])
client_only = require_roles(ROLE_CLIENTE)
staff = require_roles(ROLE_ADMIN, ROLE_CAJA)


# ------------------------------------------------------------------ métodos de pago
@router.get("/payments/methods", response_model=list[PaymentMethodOut])
def payment_methods(db: Session = Depends(get_db)):
    return db.scalars(select(PaymentMethod).where(PaymentMethod.is_active.is_(True)).order_by(PaymentMethod.sort_order)).all()


# ------------------------------------------------------------------ carrito (solo clientes)
@router.get("/cart", response_model=CartOut)
def get_cart(db: Session = Depends(get_db), user: User = Depends(client_only)):
    return sale_service.cart_view(db, client_of(user))


@router.post("/cart/items", response_model=CartOut)
def add_item(data: CartItemIn, db: Session = Depends(get_db), user: User = Depends(client_only)):
    return sale_service.add_to_cart(db, client_of(user), data.product_id, data.quantity)


@router.put("/cart/items/{product_id}", response_model=CartOut)
def set_item(product_id: int, data: CartQtyIn, db: Session = Depends(get_db), user: User = Depends(client_only)):
    return sale_service.set_cart_quantity(db, client_of(user), product_id, data.quantity)


@router.delete("/cart/items/{product_id}", response_model=CartOut)
def remove_item(product_id: int, db: Session = Depends(get_db), user: User = Depends(client_only)):
    return sale_service.remove_from_cart(db, client_of(user), product_id)


@router.delete("/cart", response_model=CartOut)
def clear(db: Session = Depends(get_db), user: User = Depends(client_only)):
    return sale_service.clear_cart(db, client_of(user))


@router.post("/cart/checkout", response_model=SaleOut, status_code=201)
def checkout(data: CheckoutIn, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(client_only),
             meta: RequestMeta = Depends(get_request_meta)):
    client_of(user)
    return sale_service.checkout(db, user, data.payment_method, data.payment, meta, tasks)


# ------------------------------------------------------------------ ventas
@router.get("/sales", response_model=Page[SaleOut])
def list_sales(
    status: Literal["PAGADA", "PENDIENTE_PAGO", "ANULADA"] | None = None,
    channel: Literal["ONLINE", "MOSTRADOR"] | None = None,
    method: Literal["ONLINE", "YAPE", "PLIN", "EFECTIVO", "LOCAL"] | None = None,
    client: str | None = Query(None, max_length=60),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(ROLE_ADMIN, ROLE_CAJA, ROLE_CLIENTE)),
):
    items, total = sale_service.list_sales(db, user, status=status, channel=channel, method=method, client_q=client,
                                           date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/sales", response_model=SaleOut, status_code=201, summary="Venta de mostrador")
def counter_sale(data: CounterSaleIn, tasks: BackgroundTasks, db: Session = Depends(get_db), actor: User = Depends(staff),
                 meta: RequestMeta = Depends(get_request_meta)):
    return sale_service.counter_sale(db, data, actor, meta, tasks)


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sale_service.get_sale_for_user(db, sale_id, user)
    return sale_service.sale_out(db, sale_id)


@router.get("/sales/{sale_id}/receipt.pdf", response_class=Response, summary="Comprobante en PDF")
def receipt_pdf(sale_id: int, download: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sale = sale_service.get_sale_for_user(db, sale_id, user)
    pdf = render_receipt_pdf(sale, get_setting(db, "business"))
    disposition = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="comprobante-{sale.receipt.code}.pdf"',
                             "Cache-Control": "private, no-store"})


@router.post("/sales/{sale_id}/confirm-payment", response_model=SaleOut)
def confirm_payment(sale_id: int, data: ConfirmPaymentIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
                    actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    return sale_service.confirm_payment(db, sale_id, data.payment_method, data.payment, actor, meta, tasks)


@router.post("/sales/{sale_id}/cancel", response_model=SaleOut)
def cancel_sale(sale_id: int, data: CancelSaleIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(ROLE_ADMIN, ROLE_CAJA, ROLE_CLIENTE)),
                meta: RequestMeta = Depends(get_request_meta)):
    return sale_service.cancel_sale(db, sale_id, data.reason, user, meta)
