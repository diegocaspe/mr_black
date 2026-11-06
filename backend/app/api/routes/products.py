from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestMeta, get_request_meta, require_roles
from app.core.errors import NotFound
from app.core.images import read_image_body
from app.models.user import ROLE_ADMIN, ROLE_CAJA, User
from app.schemas.common import Message
from app.schemas.product import (
    BulkMinStockIn,
    CategoryIn,
    CategoryOut,
    InventorySummaryOut,
    MovementIn,
    MovementOut,
    ProductCreateIn,
    ProductImageOrderIn,
    ProductImageUrlIn,
    ProductIn,
    ProductOut,
    ProductPublicOut,
    ProductStatusIn,
)
from app.services import product_service

router = APIRouter(prefix="/api", tags=["Productos e inventario"])
admin_only = require_roles(ROLE_ADMIN)
staff = require_roles(ROLE_ADMIN, ROLE_CAJA)


# ------------------------------------------------------------------ categorías
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return product_service.list_categories(db)


@router.get("/categories/all", response_model=list[CategoryOut])
def list_all_categories(db: Session = Depends(get_db), _: User = Depends(staff)):
    return product_service.list_categories(db, include_inactive=True)


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                    meta: RequestMeta = Depends(get_request_meta)):
    return product_service.save_category(db, data, actor, meta)


@router.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, data: CategoryIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                    meta: RequestMeta = Depends(get_request_meta)):
    return product_service.save_category(db, data, actor, meta, category_id)


# ------------------------------------------------------------------ productos
@router.get("/products", response_model=list[ProductPublicOut], summary="Tienda pública (solo activos)")
def public_products(q: str | None = Query(None, max_length=60), category_id: int | None = None, db: Session = Depends(get_db)):
    return product_service.list_products(db, public=True, q=q, category_id=category_id)


@router.get("/products/{product_id}", response_model=ProductPublicOut)
def public_product(product_id: int, db: Session = Depends(get_db)):
    p = product_service.get_product(db, product_id)
    if not p.is_active:
        raise NotFound("El producto no existe o no está disponible.")
    return p


@router.get("/admin/products", response_model=list[ProductOut], summary="Gestión de productos (incluye inactivos)")
def admin_products(q: str | None = Query(None, max_length=60), category_id: int | None = None,
                   stock: Literal["bajo", "agotado", "alerta"] | None = None, active: bool | None = None,
                   db: Session = Depends(get_db), _: User = Depends(staff)):
    return product_service.list_products(db, public=False, q=q, category_id=category_id, stock=stock, active=active)


@router.get("/admin/products/{product_id}", response_model=ProductOut)
def admin_product(product_id: int, db: Session = Depends(get_db), _: User = Depends(staff)):
    return product_service.get_product(db, product_id)


@router.post("/admin/products", response_model=ProductOut, status_code=201)
def create_product(data: ProductCreateIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                   meta: RequestMeta = Depends(get_request_meta)):
    return product_service.create_product(db, data, actor, meta)


@router.put("/admin/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                   meta: RequestMeta = Depends(get_request_meta)):
    return product_service.update_product(db, product_id, data, actor, meta)


@router.patch("/admin/products/{product_id}/status", response_model=ProductOut)
def set_product_status(product_id: int, data: ProductStatusIn, db: Session = Depends(get_db),
                       actor: User = Depends(admin_only), meta: RequestMeta = Depends(get_request_meta)):
    return product_service.set_product_status(db, product_id, data.is_active, actor, meta)


# ------------------------------------------------------------------ fotos del producto (personal: admin y caja)
@router.get("/product-images/{image_id}", response_class=Response, summary="Foto de producto (pública, cacheable)")
def product_image(image_id: int, db: Session = Depends(get_db)):
    img = product_service.get_image(db, image_id)
    # Cada foto es inmutable (un cambio crea un id nuevo), así que puede cachearse indefinidamente.
    return Response(img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/admin/products/{product_id}/images", response_model=ProductOut, status_code=201,
             summary="Subir foto: cuerpo binario image/jpeg, image/png o image/webp (máx. 2 MB)")
async def upload_product_image(product_id: int, request: Request, db: Session = Depends(get_db),
                               actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    data = await read_image_body(request)
    return await run_in_threadpool(product_service.add_image, db, product_id, data, actor, meta)


@router.delete("/admin/products/{product_id}/images/{image_id}", response_model=ProductOut)
def delete_product_image(product_id: int, image_id: int, db: Session = Depends(get_db), actor: User = Depends(staff),
                         meta: RequestMeta = Depends(get_request_meta)):
    return product_service.delete_image(db, product_id, image_id, actor, meta)


@router.put("/admin/products/{product_id}/images/order", response_model=ProductOut)
def order_product_images(product_id: int, data: ProductImageOrderIn, db: Session = Depends(get_db),
                         actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    return product_service.reorder_images(db, product_id, data.image_ids, actor, meta)


@router.patch("/admin/products/{product_id}/image", response_model=ProductOut, summary="Foto por enlace (solo ese campo)")
def set_product_image_url(product_id: int, data: ProductImageUrlIn, db: Session = Depends(get_db),
                          actor: User = Depends(staff), meta: RequestMeta = Depends(get_request_meta)):
    return product_service.set_image_url(db, product_id, data.image_url, actor, meta)


# ------------------------------------------------------------------ inventario
@router.get("/inventory/summary", response_model=InventorySummaryOut)
def inventory_summary(db: Session = Depends(get_db), _: User = Depends(staff)):
    return product_service.inventory_summary(db)


@router.get("/inventory/alerts", response_model=list[ProductOut])
def inventory_alerts(db: Session = Depends(get_db), _: User = Depends(staff)):
    return product_service.list_products(db, public=False, stock="alerta", active=True)


@router.get("/inventory/movements", response_model=list[MovementOut])
def list_movements(product_id: int | None = None,
                   movement_type: Literal["ENTRADA", "SALIDA", "AJUSTE", "VENTA", "DEVOLUCION"] | None = None,
                   date_from: date | None = None, date_to: date | None = None,
                   db: Session = Depends(get_db), _: User = Depends(staff)):
    return product_service.list_movements(db, product_id, movement_type, date_from, date_to)


@router.post("/inventory/movements", response_model=MovementOut, status_code=201)
def register_movement(data: MovementIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                      meta: RequestMeta = Depends(get_request_meta)):
    return product_service.register_movement(db, data, actor, meta)


@router.post("/inventory/min-stock", response_model=Message)
def bulk_min_stock(data: BulkMinStockIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                   meta: RequestMeta = Depends(get_request_meta)):
    n = product_service.apply_min_stock_to_all(db, data.min_stock, actor, meta)
    return Message(message=f"Stock mínimo {data.min_stock} aplicado a {n} producto(s). Alertas recalculadas.")
