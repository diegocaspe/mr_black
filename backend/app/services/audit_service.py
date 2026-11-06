from typing import Any

from sqlalchemy.orm import Session

from app.core.deps import RequestMeta
from app.models.audit import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def audit(
    db: Session,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id: Any = None,
    details: dict | None = None,
    meta: RequestMeta | None = None,
) -> None:
    """Agrega un registro de auditoría a la transacción actual (se confirma con ella)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=_jsonable(details) if details else None,
            ip_address=meta.ip if meta else None,
            user_agent=meta.user_agent if meta else None,
        )
    )


def diff(before: dict, after: dict) -> dict:
    """Devuelve solo los campos que cambiaron: {campo: [antes, después]}."""
    return {k: [before.get(k), after.get(k)] for k in after if before.get(k) != after.get(k)}
