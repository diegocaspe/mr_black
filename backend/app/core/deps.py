from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import SESSION_COOKIE, decode_access_token
from app.models.user import ROLE_BARBERO, ROLE_CLIENTE, User, UserSession


@dataclass
class RequestMeta:
    ip: str | None
    user_agent: str | None


def get_request_meta(request: Request) -> RequestMeta:
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "")[:255] or None
    return RequestMeta(ip=ip, user_agent=ua)


def _load_user_from_cookie(request: Request, db: Session) -> tuple[User, UserSession] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    session = db.get(UserSession, payload["sid"])
    now = datetime.now(UTC)
    if not session or session.revoked_at is not None or session.expires_at <= now:
        return None
    if str(session.user_id) != payload["sub"]:
        return None
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        return None
    return user, session


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    loaded = _load_user_from_cookie(request, db)
    if not loaded:
        return None
    request.state.session_id = loaded[1].id
    return loaded[0]


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_optional_user(request, db)
    if user is None:
        raise Unauthorized()
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Dependencia que exige uno de los roles indicados. Se valida SIEMPRE en el servidor."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role_code not in roles:
            raise Forbidden()
        return user

    return checker


def client_of(user: User):
    if user.role_code != ROLE_CLIENTE or user.client is None:
        raise Forbidden("Esta acción está disponible solo para clientes.")
    return user.client


def barber_of(user: User):
    if user.role_code != ROLE_BARBERO or user.barber is None:
        raise Forbidden("Tu cuenta no está asociada a un barbero.")
    return user.barber


def active_user_ids_with_roles(db: Session, roles: tuple[str, ...]) -> list[int]:
    from app.models.user import Role

    return list(
        db.scalars(select(User.id).join(Role).where(Role.code.in_(roles), User.is_active.is_(True))).all()
    )
