from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Métodos de pago (catálogo en tabla payment_methods)
PM_ONLINE = "ONLINE"
PM_YAPE = "YAPE"
PM_PLIN = "PLIN"
PM_EFECTIVO = "EFECTIVO"
PM_LOCAL = "LOCAL"

SALE_PAGADA = "PAGADA"
SALE_PENDIENTE_PAGO = "PENDIENTE_PAGO"
SALE_ANULADA = "ANULADA"

CHANNEL_ONLINE = "ONLINE"
CHANNEL_MOSTRADOR = "MOSTRADOR"

PAYMENT_APROBADO = "APROBADO"
PAYMENT_PENDIENTE = "PENDIENTE"
PAYMENT_ANULADO = "ANULADO"


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    # immediate=True: se aprueba en el momento (simulado). False: se cobra en el local.
    immediate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    online_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    counter_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("total > 0", name="total_positive"),
        CheckConstraint("subtotal > 0", name="subtotal_positive"),
        Index("ix_sales_created_at", "created_at"),
        Index("ix_sales_client_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_method: Mapped[str] = mapped_column(ForeignKey("payment_methods.code"), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))

    client = relationship("Client", lazy="joined")
    method = relationship("PaymentMethod", lazy="joined")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan", order_by="SaleItem.id")
    payments = relationship("Payment", back_populates="sale", order_by="Payment.id")
    receipt = relationship("Receipt", back_populates="sale", uselist=False)
    creator = relationship("User", lazy="joined")


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        CheckConstraint(
            "(product_id IS NOT NULL AND service_id IS NULL) OR (product_id IS NULL AND service_id IS NOT NULL)",
            name="product_xor_service",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    sale = relationship("Sale", back_populates="items")

    @property
    def item_type(self) -> str:
        return "PRODUCTO" if self.product_id else "SERVICIO"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True)
    method_code: Mapped[str] = mapped_column(ForeignKey("payment_methods.code"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(60))
    payer_detail: Mapped[str | None] = mapped_column(String(60))  # p.ej. "Visa •••• 4242" o "Yape 9•••••321"
    processed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sale = relationship("Sale", back_populates="payments")


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (UniqueConstraint("series", "number", name="uq_receipts_series_number"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"), unique=True, nullable=False)
    series: Mapped[str] = mapped_column(String(4), nullable=False, default="B001")
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(60), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(9))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sale = relationship("Sale", back_populates="receipt")

    @property
    def code(self) -> str:
        return f"{self.series}-{self.number:08d}"
