from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import RequestMeta, active_user_ids_with_roles
from app.core.errors import BadRequest, Conflict, NotFound
from app.models.product import (
    MOVEMENT_ENTRADA,
    MOVEMENT_SALIDA,
    InventoryMovement,
    Product,
    ProductCategory,
    ProductImage,
)
from app.models.user import ROLE_ADMIN, User
from app.schemas.product import CategoryIn, InventorySummaryOut, MovementIn, ProductCreateIn, ProductIn
from app.services import image_service
from app.services.audit_service import audit, diff
from app.services.notification_service import notify_many
from app.services.settings_service import set_setting

# ------------------------------------------------------------------ categorías


def list_categories(db: Session, include_inactive: bool = False) -> list[ProductCategory]:
    stmt = select(ProductCategory).order_by(ProductCategory.name)
    if not include_inactive:
        stmt = stmt.where(ProductCategory.is_active.is_(True))
    return list(db.scalars(stmt).all())


def save_category(db: Session, data: CategoryIn, actor: User, meta: RequestMeta, category_id: int | None = None) -> ProductCategory:
    dup = select(ProductCategory.id).where(func.lower(ProductCategory.name) == data.name.lower())
    if category_id:
        dup = dup.where(ProductCategory.id != category_id)
    if db.scalar(dup):
        raise Conflict("Ya existe una categoría con ese nombre.", fields={"name": "Nombre duplicado."})
    if category_id:
        cat = db.get(ProductCategory, category_id)
        if not cat:
            raise NotFound("La categoría no existe.")
        cat.name, cat.is_active = data.name, data.is_active
        action = "CATEGORIA_EDITADA"
    else:
        cat = ProductCategory(name=data.name, is_active=data.is_active)
        db.add(cat)
        action = "CATEGORIA_CREADA"
    db.flush()
    audit(db, actor.id, action, "category", cat.id, data.model_dump(), meta)
    db.commit()
    db.refresh(cat)
    return cat


# ------------------------------------------------------------------ productos


def get_product(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if not p:
        raise NotFound("El producto no existe.")
    return p


def list_products(
    db: Session,
    *,
    public: bool,
    q: str | None = None,
    category_id: int | None = None,
    stock: str | None = None,
    active: bool | None = None,
) -> list[Product]:
    stmt = select(Product).join(ProductCategory).order_by(Product.name)
    if public:
        # 0024798: los productos dados de baja no aparecen en la tienda pública.
        stmt = stmt.where(Product.is_active.is_(True), ProductCategory.is_active.is_(True))
    elif active is not None:
        stmt = stmt.where(Product.is_active.is_(active))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Product.name).like(like), func.lower(Product.description).like(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if stock == "bajo":
        stmt = stmt.where(Product.stock <= Product.min_stock, Product.stock > 0)
    elif stock == "agotado":
        stmt = stmt.where(Product.stock == 0)
    elif stock == "alerta":
        stmt = stmt.where(Product.stock <= Product.min_stock)
    return list(db.scalars(stmt).unique().all())


def _check_category(db: Session, category_id: int) -> None:
    cat = db.get(ProductCategory, category_id)
    if not cat:
        raise BadRequest("La categoría seleccionada no existe.", fields={"category_id": "Categoría inválida."})


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Product.id).where(func.lower(Product.name) == name.lower())
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    return db.scalar(stmt) is not None


def _snapshot(p: Product) -> dict:
    return {
        "name": p.name,
        "description": p.description,
        "category_id": p.category_id,
        "price": str(p.price),
        "image_url": p.image_url,
        "icon": p.icon,
        "min_stock": p.min_stock,
        "is_active": p.is_active,
    }


def low_stock_alert(db: Session, p: Product, stock_before: int, min_before: int | None = None) -> None:
    """Notifica a los administradores cuando un producto activo cruza el umbral de stock mínimo."""
    was_low = stock_before <= (min_before if min_before is not None else p.min_stock)
    if p.is_active and p.stock <= p.min_stock and not was_low:
        title = "Producto agotado" if p.stock == 0 else "Stock bajo"
        notify_many(
            db,
            active_user_ids_with_roles(db, (ROLE_ADMIN,)),
            "STOCK_BAJO",
            title,
            f"{p.name}: quedan {p.stock} unidad(es) (mínimo {p.min_stock}).",
            "#/inventario",
        )


def create_product(db: Session, data: ProductCreateIn, actor: User, meta: RequestMeta) -> Product:
    _check_category(db, data.category_id)
    if _name_taken(db, data.name):
        raise Conflict("Ya existe un producto con ese nombre.", fields={"name": "Nombre duplicado."})
    payload = data.model_dump(exclude={"initial_stock"})
    p = Product(**payload, stock=data.initial_stock)
    db.add(p)
    db.flush()
    if data.initial_stock:
        db.add(InventoryMovement(product_id=p.id, movement_type=MOVEMENT_ENTRADA, quantity=data.initial_stock,
                                 stock_before=0, stock_after=data.initial_stock, reason="Stock inicial", user_id=actor.id))
    audit(db, actor.id, "PRODUCTO_CREADO", "product", p.id, {**_snapshot(p), "stock": p.stock}, meta)
    low_stock_alert(db, p, stock_before=p.min_stock + 1)
    db.commit()
    db.refresh(p)
    return p


def update_product(db: Session, product_id: int, data: ProductIn, actor: User, meta: RequestMeta) -> Product:
    p = get_product(db, product_id)
    _check_category(db, data.category_id)
    if _name_taken(db, data.name, exclude_id=p.id):
        raise Conflict("Ya existe un producto con ese nombre.", fields={"name": "Nombre duplicado."})
    before = _snapshot(p)
    min_before = p.min_stock
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.flush()
    changes = diff(before, _snapshot(p))
    if changes:
        action = "PRODUCTO_EDITADO"
        if "is_active" in changes:
            action = "PRODUCTO_ACTIVADO" if p.is_active else "PRODUCTO_DESACTIVADO"
        audit(db, actor.id, action, "product", p.id, changes, meta)
    low_stock_alert(db, p, stock_before=p.stock, min_before=min_before)
    db.commit()
    db.refresh(p)
    return p


# ------------------------------------------------------------------ fotos del producto
GALLERY = image_service.Gallery(model=ProductImage, owner_fk="product_id", entity="product", action_prefix="PRODUCTO")


def add_image(db: Session, product_id: int, data: bytes, actor: User, meta: RequestMeta) -> Product:
    return image_service.add_image(db, GALLERY, get_product(db, product_id), data, actor, meta)


def delete_image(db: Session, product_id: int, image_id: int, actor: User, meta: RequestMeta) -> Product:
    return image_service.delete_image(db, GALLERY, get_product(db, product_id), image_id, actor, meta)


def reorder_images(db: Session, product_id: int, image_ids: list[int], actor: User, meta: RequestMeta) -> Product:
    return image_service.reorder_images(db, GALLERY, get_product(db, product_id), image_ids, actor, meta)


def set_image_url(db: Session, product_id: int, image_url: str | None, actor: User, meta: RequestMeta) -> Product:
    """Cambia solo la foto por enlace (el personal de caja no puede editar precio ni otros datos)."""
    p = get_product(db, product_id)
    if p.image_url != image_url:
        audit(db, actor.id, "PRODUCTO_EDITADO", "product", p.id, {"image_url": [p.image_url, image_url]}, meta)
        p.image_url = image_url
        db.commit()
    return image_service.refreshed(db, p)


def get_image(db: Session, image_id: int) -> ProductImage:
    return image_service.get_image(db, ProductImage, image_id)


def set_product_status(db: Session, product_id: int, is_active: bool, actor: User, meta: RequestMeta) -> Product:
    """0024798: cambia y persiste realmente el estado; la respuesta es el producto releído de la BD."""
    p = get_product(db, product_id)
    if p.is_active != is_active:
        p.is_active = is_active
        audit(db, actor.id, "PRODUCTO_ACTIVADO" if is_active else "PRODUCTO_DESACTIVADO", "product", p.id, None, meta)
        db.commit()
    db.refresh(p)
    return p


# ------------------------------------------------------------------ inventario


def apply_stock_change(
    db: Session,
    p: Product,
    delta: int,
    movement_type: str,
    actor_id: int | None,
    reason: str | None = None,
    sale_id: int | None = None,
) -> InventoryMovement:
    """Único punto que modifica stock. El producto debe estar bloqueado (FOR UPDATE) por el llamador."""
    before = p.stock
    after = before + delta
    if after < 0:
        raise Conflict(f"Stock insuficiente: quedan {before} unidades de {p.name}.", code="insufficient_stock")
    p.stock = after
    mv = InventoryMovement(product_id=p.id, movement_type=movement_type, quantity=delta, stock_before=before,
                           stock_after=after, reason=reason, sale_id=sale_id, user_id=actor_id)
    db.add(mv)
    low_stock_alert(db, p, stock_before=before)
    return mv


def lock_product(db: Session, product_id: int) -> Product:
    p = db.scalars(
        select(Product).where(Product.id == product_id).with_for_update(of=Product)
        .execution_options(populate_existing=True)
    ).unique().first()
    if not p:
        raise NotFound("El producto no existe.")
    return p


def register_movement(db: Session, data: MovementIn, actor: User, meta: RequestMeta) -> InventoryMovement:
    p = lock_product(db, data.product_id)
    if data.movement_type == MOVEMENT_ENTRADA:
        delta = data.quantity
    elif data.movement_type == MOVEMENT_SALIDA:
        delta = -data.quantity
        if data.quantity > p.stock:
            raise Conflict(f"Stock insuficiente: quedan {p.stock} unidades.", code="insufficient_stock",
                           fields={"quantity": f"Máximo {p.stock} unidades."})
    else:  # AJUSTE: quantity es el conteo físico final
        delta = data.quantity - p.stock
        if delta == 0:
            raise BadRequest("El stock contado es igual al actual; no hay nada que ajustar.", fields={"quantity": "Sin cambios."})
    mv = apply_stock_change(db, p, delta, data.movement_type, actor.id, data.reason)
    db.flush()
    audit(db, actor.id, f"INVENTARIO_{data.movement_type}", "product", p.id,
          {"cantidad": delta, "stock_antes": mv.stock_before, "stock_despues": mv.stock_after, "motivo": data.reason}, meta)
    db.commit()
    db.refresh(mv)
    return mv


def list_movements(db: Session, product_id: int | None, movement_type: str | None, date_from=None, date_to=None,
                   limit: int = 200) -> list[InventoryMovement]:
    from app.core.timeutils import day_bounds_utc

    stmt = select(InventoryMovement).order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
    if product_id:
        stmt = stmt.where(InventoryMovement.product_id == product_id)
    if movement_type:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type)
    if date_from:
        stmt = stmt.where(InventoryMovement.created_at >= day_bounds_utc(date_from)[0])
    if date_to:
        stmt = stmt.where(InventoryMovement.created_at < day_bounds_utc(date_to)[1])
    return list(db.scalars(stmt.limit(limit)).unique().all())


def apply_min_stock_to_all(db: Session, min_stock: int, actor: User, meta: RequestMeta) -> int:
    """0024818: aplica un nuevo mínimo a todos los productos; las alertas se recalculan al instante
    porque se derivan de `stock <= min_stock` en cada consulta."""
    products = list(db.scalars(
        select(Product).with_for_update(of=Product).execution_options(populate_existing=True)
    ).unique().all())
    for p in products:
        before = p.min_stock
        p.min_stock = min_stock
        low_stock_alert(db, p, stock_before=p.stock, min_before=before)
    set_setting(db, "inventory", {"default_min_stock": min_stock}, actor.id)
    audit(db, actor.id, "STOCK_MINIMO_GLOBAL", "product", None, {"min_stock": min_stock, "productos": len(products)}, meta)
    db.commit()
    return len(products)


def inventory_summary(db: Session) -> InventorySummaryOut:
    row = db.execute(
        select(
            func.count(),
            func.count().filter(Product.is_active.is_(True)),
            func.count().filter(Product.is_active.is_(False)),
            func.count().filter(Product.is_active.is_(True), Product.stock <= Product.min_stock, Product.stock > 0),
            func.count().filter(Product.is_active.is_(True), Product.stock == 0),
            func.coalesce(func.sum(case((Product.is_active.is_(True), Product.stock * Product.price), else_=0)), 0),
        )
    ).one()
    return InventorySummaryOut(
        total_products=row[0], active_products=row[1], inactive_products=row[2],
        low_stock=row[3], out_of_stock=row[4], inventory_value=row[5],
    )
