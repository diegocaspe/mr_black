from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.core.validators import CategoryName, FieldErrors, ImageUrl, Price, ProductName, ShortText
from app.schemas.catalog import ICON_PATTERN
from app.schemas.common import ImageOrderIn, ImageOut, InputModel, ORMModel

# Alias con nombre de producto (mismo contrato que la galería genérica).
ProductImageOut = ImageOut
ProductImageOrderIn = ImageOrderIn

MAX_STOCK = 100_000


class CategoryIn(InputModel):
    name: CategoryName
    is_active: bool = True


class CategoryOut(ORMModel):
    id: int
    name: str
    is_active: bool


class ProductIn(InputModel):
    name: ProductName
    description: ShortText = None
    category_id: int
    price: Price
    image_url: ImageUrl = None
    icon: str = Field(default="fa-box", pattern=ICON_PATTERN)
    min_stock: int = Field(ge=0, le=MAX_STOCK)
    is_active: bool = True


class ProductCreateIn(ProductIn):
    initial_stock: int = Field(default=0, ge=0, le=MAX_STOCK)


class ProductStatusIn(InputModel):
    is_active: bool


class ProductImageUrlIn(InputModel):
    """Foto principal por enlace (https o /assets/…); null la quita."""

    image_url: ImageUrl = None


class ProductPublicOut(ORMModel):
    id: int
    name: str
    description: str | None
    category: CategoryOut
    price: Decimal
    image_url: str | None
    images: list[ProductImageOut] = []
    icon: str
    stock: int
    stock_status: str


class ProductOut(ProductPublicOut):
    min_stock: int
    is_active: bool
    is_low_stock: bool
    created_at: datetime
    updated_at: datetime


class MovementIn(InputModel):
    product_id: int
    movement_type: Literal["ENTRADA", "SALIDA", "AJUSTE"]
    quantity: int = Field(ge=0, le=MAX_STOCK, description="ENTRADA/SALIDA: unidades; AJUSTE: stock final contado")
    reason: ShortText = None

    @model_validator(mode="after")
    def check(self):
        if self.movement_type in ("ENTRADA", "SALIDA") and self.quantity <= 0:
            raise FieldErrors({"quantity": "La cantidad debe ser mayor a 0."})
        if self.movement_type in ("SALIDA", "AJUSTE") and not self.reason:
            raise FieldErrors({"reason": "Indica el motivo de la salida o ajuste."})
        return self


class BulkMinStockIn(InputModel):
    min_stock: int = Field(ge=0, le=MAX_STOCK)


class ProductRef(ORMModel):
    id: int
    name: str


class UserRef(ORMModel):
    id: int
    full_name: str


class MovementOut(ORMModel):
    id: int
    product: ProductRef
    movement_type: str
    quantity: int
    stock_before: int
    stock_after: int
    reason: str | None
    sale_id: int | None
    user: UserRef | None
    created_at: datetime


class InventorySummaryOut(ORMModel):
    total_products: int
    active_products: int
    inactive_products: int
    low_stock: int
    out_of_stock: int
    inventory_value: Decimal
