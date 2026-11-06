from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from app.core.validators import PersonName, Phone, ShortText
from app.schemas.common import InputModel, ORMModel

MethodCode = Literal["ONLINE", "YAPE", "PLIN", "EFECTIVO", "LOCAL"]


class PaymentMethodOut(ORMModel):
    code: str
    name: str
    description: str | None
    immediate: bool
    online_allowed: bool
    counter_allowed: bool


class PaymentDetailsIn(InputModel):
    """Datos del pago simulado. Nunca se almacena el número completo de tarjeta ni el CVV."""

    card_number: str | None = Field(default=None, max_length=30)
    card_holder: PersonName | None = None
    card_expiry: str | None = Field(default=None, max_length=7)
    card_cvv: str | None = Field(default=None, max_length=4)
    wallet_phone: Phone | None = None
    approval_code: str | None = Field(default=None, max_length=6)
    amount_received: Decimal | None = Field(default=None, ge=0, le=100000, decimal_places=2)


class CheckoutIn(InputModel):
    # 0024817: un solo método (valor único, no lista) → mutuamente excluyentes por contrato.
    payment_method: MethodCode
    payment: PaymentDetailsIn = Field(default_factory=PaymentDetailsIn)


class CartItemIn(InputModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=999)


class CartQtyIn(InputModel):
    quantity: int = Field(ge=1, le=999)


class CartLineOut(ORMModel):
    product_id: int
    name: str
    icon: str
    image_url: str | None
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    stock: int
    available: bool
    issue: str | None = None


class CartOut(ORMModel):
    items: list[CartLineOut]
    item_count: int
    subtotal: Decimal
    total: Decimal
    can_checkout: bool
    issues: list[str]


class CounterItemIn(InputModel):
    product_id: int
    quantity: int = Field(ge=1, le=999)


class CounterSaleIn(InputModel):
    client_id: int | None = None
    items: list[CounterItemIn] = Field(min_length=1, max_length=50)
    payment_method: MethodCode
    payment: PaymentDetailsIn = Field(default_factory=PaymentDetailsIn)
    notes: ShortText = None

    @field_validator("items")
    @classmethod
    def unique_products(cls, v: list[CounterItemIn]):
        if len({i.product_id for i in v}) != len(v):
            raise ValueError("Cada producto debe aparecer una sola vez; ajusta la cantidad.")
        return v


class ChargeAppointmentIn(InputModel):
    payment_method: MethodCode
    payment: PaymentDetailsIn = Field(default_factory=PaymentDetailsIn)


class ConfirmPaymentIn(InputModel):
    payment_method: Literal["EFECTIVO", "YAPE", "PLIN", "ONLINE"]
    payment: PaymentDetailsIn = Field(default_factory=PaymentDetailsIn)


class CancelSaleIn(InputModel):
    reason: ShortText = None


class SaleItemOut(ORMModel):
    id: int
    product_id: int | None
    service_id: int | None
    appointment_id: int | None
    item_type: str
    description: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class PaymentOut(ORMModel):
    id: int
    method_code: str
    amount: Decimal
    status: str
    reference: str | None
    payer_detail: str | None
    created_at: datetime
    processed_at: datetime | None


class ClientRefOut(ORMModel):
    id: int
    full_name: str
    phone: str


class SaleOut(ORMModel):
    id: int
    receipt_code: str | None = None
    client: ClientRefOut | None
    channel: str
    status: str
    payment_method: str
    payment_method_name: str | None = None
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    notes: str | None
    created_at: datetime
    paid_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_by_name: str | None = None
    items: list[SaleItemOut]
    payments: list[PaymentOut]
    change_due: Decimal | None = None
