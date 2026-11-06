from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestMeta, get_request_meta, require_roles
from app.models.user import ROLE_ADMIN, User
from app.schemas.common import Message
from app.schemas.user import AdminPasswordIn, RoleCode, UserCreateIn, UserOut, UserStatusIn, UserUpdateIn
from app.services import user_service

# Toda la gestión de usuarios es exclusiva de ADMIN (verificado en el servidor, no solo ocultando botones).
router = APIRouter(prefix="/api/users", tags=["Usuarios"])
admin_only = require_roles(ROLE_ADMIN)


@router.get("", response_model=list[UserOut])
def list_users(q: str | None = Query(None, max_length=60), role: RoleCode | None = None, active: bool | None = None,
               db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return [user_service.to_out(u) for u in user_service.list_users(db, q, role, active)]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return user_service.to_out(user_service.get_user(db, user_id))


@router.post("", response_model=UserOut, status_code=201)
def create_user(data: UserCreateIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                meta: RequestMeta = Depends(get_request_meta)):
    return user_service.to_out(user_service.create_user(db, data, actor, meta))


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdateIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                meta: RequestMeta = Depends(get_request_meta)):
    return user_service.to_out(user_service.update_user(db, user_id, data, actor, meta))


@router.patch("/{user_id}/status", response_model=UserOut)
def set_status(user_id: int, data: UserStatusIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
               meta: RequestMeta = Depends(get_request_meta)):
    return user_service.to_out(user_service.set_user_status(db, user_id, data.is_active, actor, meta))


@router.post("/{user_id}/password", response_model=Message)
def set_password(user_id: int, data: AdminPasswordIn, db: Session = Depends(get_db), actor: User = Depends(admin_only),
                 meta: RequestMeta = Depends(get_request_meta)):
    user_service.admin_set_password(db, user_id, data.password, actor, meta)
    return Message(message="Contraseña actualizada. Se cerraron las sesiones activas del usuario.")
