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
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import StoredImageMixin, TimestampMixin

MOVEMENT_ENTRADA = "ENTRADA"
MOVEMENT_SALIDA = "SALIDA"
MOVEMENT_AJUSTE = "AJUSTE"
MOVEMENT_VENTA = "VENTA"
MOVEMENT_DEVOLUCION = "DEVOLUCION"
MOVEMENT_TYPES = (MOVEMENT_ENTRADA, MOVEMENT_SALIDA, MOVEMENT_AJUSTE, MOVEMENT_VENTA, MOVEMENT_DEVOLUCION)


class ProductCategory(TimestampMixin, Base):
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0.10", name="price_min"),
        CheckConstraint("stock >= 0", name="stock_non_negative"),
        CheckConstraint("min_stock >= 0", name="min_stock_non_negative"),
        Index("uq_products_name_lower", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="fa-box", server_default="fa-box")
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    category = relationship("ProductCategory", lazy="joined", innerjoin=True)
    # Fotos subidas por el personal (galería). Los bytes no se cargan aquí: ver ProductImage.data.
    images = relationship("ProductImage", lazy="selectin", order_by="ProductImage.position",
                          cascade="all, delete-orphan", passive_deletes=True)

    @property
    def cover_url(self) -> str | None:
        """Portada: la foto por enlace si existe; si no, la primera foto subida."""
        return self.image_url or (self.images[0].url if self.images else None)

    @property
    def is_low_stock(self) -> bool:
        return self.stock <= self.min_stock

    @property
    def stock_status(self) -> str:
        if self.stock == 0:
            return "AGOTADO"
        if self.stock <= self.min_stock:
            return "BAJO"
        return "OK"


class ProductImage(StoredImageMixin, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_product_images_product_position", "product_id", "position"),
    )
    url_base = "/api/product-images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0", name="quantity_non_zero"),
        CheckConstraint("stock_after >= 0", name="stock_after_non_negative"),
        Index("ix_inventory_movements_product_created", "product_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)  # positivo entra, negativo sale
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="SET NULL"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("Product", lazy="joined")
    user = relationship("User", lazy="joined")
