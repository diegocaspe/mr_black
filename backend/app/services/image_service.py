"""Galerías de fotos guardadas en la BD (productos y servicios).

Cada dueño (Product, Service) tiene una relación `images` ordenada por `position` y un modelo de
foto basado en `StoredImageMixin`. Todas las operaciones quedan en la auditoría con el prefijo
del dueño (p. ej. PRODUCTO_FOTO_AGREGADA, SERVICIO_FOTO_ELIMINADA).
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from app.core.deps import RequestMeta
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.images import MAX_IMAGES_PER_ITEM, validated_image_type
from app.models.user import User
from app.services.audit_service import audit


@dataclass(frozen=True)
class Gallery:
    model: type        # modelo de foto (ProductImage, ServiceImage)
    owner_fk: str      # columna FK al dueño (product_id, service_id)
    entity: str        # entidad en la auditoría (product, service)
    action_prefix: str  # PRODUCTO, SERVICIO


def refreshed(db: Session, owner):
    """Relee el dueño y su galería (la sesión no expira objetos al confirmar)."""
    db.refresh(owner)
    db.refresh(owner, attribute_names=["images"])
    return owner


def add_image(db: Session, g: Gallery, owner, data: bytes, actor: User, meta: RequestMeta):
    ctype = validated_image_type(data)
    fk = getattr(g.model, g.owner_fk)
    count = db.scalar(select(func.count()).select_from(g.model).where(fk == owner.id))
    if count >= MAX_IMAGES_PER_ITEM:
        raise Conflict(f"Ya tiene el máximo de {MAX_IMAGES_PER_ITEM} fotos.", code="image_limit")
    last = db.scalar(select(func.max(g.model.position)).where(fk == owner.id)) or 0
    img = g.model(**{g.owner_fk: owner.id}, content_type=ctype, data=data, size_bytes=len(data),
                  position=last + 1, uploaded_by=actor.id)
    db.add(img)
    db.flush()
    audit(db, actor.id, f"{g.action_prefix}_FOTO_AGREGADA", g.entity, owner.id,
          {"image_id": img.id, "content_type": ctype, "size_bytes": len(data)}, meta)
    db.commit()
    return refreshed(db, owner)


def delete_image(db: Session, g: Gallery, owner, image_id: int, actor: User, meta: RequestMeta):
    img = db.get(g.model, image_id)
    if not img or getattr(img, g.owner_fk) != owner.id:
        raise NotFound("La foto no existe.")
    db.delete(img)
    audit(db, actor.id, f"{g.action_prefix}_FOTO_ELIMINADA", g.entity, owner.id, {"image_id": image_id}, meta)
    db.commit()
    return refreshed(db, owner)


def reorder_images(db: Session, g: Gallery, owner, image_ids: list[int], actor: User, meta: RequestMeta):
    current = {img.id: img for img in owner.images}
    if len(image_ids) != len(set(image_ids)) or set(image_ids) != set(current):
        raise BadRequest("El orden debe incluir todas las fotos, sin repetir.", fields={"image_ids": "Lista inválida."})
    for pos, image_id in enumerate(image_ids, start=1):
        current[image_id].position = pos
    audit(db, actor.id, f"{g.action_prefix}_FOTOS_ORDENADAS", g.entity, owner.id, {"image_ids": image_ids}, meta)
    db.commit()
    return refreshed(db, owner)


def get_image(db: Session, model: type, image_id: int):
    """Foto con sus bytes cargados (para servirla)."""
    img = db.scalar(select(model).options(undefer(model.data)).where(model.id == image_id))
    if not img:
        raise NotFound("La foto no existe.")
    return img
