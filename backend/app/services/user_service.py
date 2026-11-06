from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import RequestMeta
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.security import hash_password
from app.models.barber import Barber
from app.models.client import Client
from app.models.user import ROLE_ADMIN, ROLE_BARBERO, ROLE_CLIENTE, Role, User
from app.schemas.user import UserCreateIn, UserOut, UserUpdateIn
from app.services.audit_service import audit, diff
from app.services.auth_service import ensure_unique_identity, revoke_all_sessions


def to_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.barber_id = user.barber.id if user.barber else None
    out.client_id = user.client.id if user.client else None
    out.phone = user.client.phone if user.client else None
    return out


def _snapshot(user: User) -> dict:
    return {
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "role": user.role_code,
        "is_active": user.is_active,
        "barber_id": user.barber.id if user.barber else None,
        "phone": user.client.phone if user.client else None,
    }


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("El usuario no existe.")
    return user


def list_users(db: Session, q: str | None, role: str | None, active: bool | None) -> list[User]:
    stmt = select(User).join(Role).order_by(User.created_at.desc())
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), User.username.like(like), User.email.like(like)))
    if role:
        stmt = stmt.where(Role.code == role)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    return list(db.scalars(stmt).unique().all())


def _role(db: Session, code: str) -> Role:
    return db.scalars(select(Role).where(Role.code == code)).one()


def _active_admin_count(db: Session, exclude_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(User).join(Role).where(Role.code == ROLE_ADMIN, User.is_active.is_(True))
    if exclude_id:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt)


def _link_barber(db: Session, user: User, barber_id: int | None) -> None:
    """Vincula la cuenta a un perfil de barbero. Si no se indica, crea uno nuevo con el nombre del usuario."""
    current = user.barber
    if barber_id:
        barber = db.get(Barber, barber_id)
        if not barber or not barber.is_active:
            raise BadRequest("El barbero seleccionado no existe o está dado de baja.", fields={"barber_id": "Barbero inválido."})
        if barber.user_id and barber.user_id != user.id:
            raise Conflict("Ese barbero ya está vinculado a otra cuenta.", fields={"barber_id": "Ya tiene una cuenta vinculada."})
        if current and current.id != barber.id:
            current.user_id = None
            db.flush()
        barber.user_id = user.id
    elif not current:
        db.add(Barber(user_id=user.id, full_name=user.full_name, is_available=True))
    db.flush()
    db.refresh(user)


def _unlink_barber(db: Session, user: User) -> None:
    if user.barber:
        user.barber.user_id = None  # el perfil y su historial de citas se conservan
        db.flush()
        db.refresh(user)


def _link_client(db: Session, user: User, phone: str | None) -> None:
    if user.client:
        if phone and phone != user.client.phone:
            ensure_unique_identity(db, phone=phone, exclude_client_id=user.client.id)
            user.client.phone = phone
        user.client.full_name = user.full_name
        user.client.email = user.email
        return
    if not phone:
        raise BadRequest("El teléfono es obligatorio para cuentas de cliente.", fields={"phone": "Ingresa el teléfono del cliente."})
    existing = db.scalars(select(Client).where(Client.phone == phone)).first()
    if existing:
        if existing.user_id and existing.user_id != user.id:
            raise Conflict("Ya existe una cuenta con ese teléfono.", fields={"phone": "Ya existe una cuenta con ese teléfono."})
        existing.user_id = user.id
        existing.email = existing.email or user.email
    else:
        db.add(Client(user_id=user.id, full_name=user.full_name, phone=phone, email=user.email))
    db.flush()
    db.refresh(user)


def _unlink_client(db: Session, user: User) -> None:
    if user.client:
        user.client.user_id = None  # la ficha del cliente y su historial se conservan
        db.flush()
        db.refresh(user)


def create_user(db: Session, data: UserCreateIn, actor: User, meta: RequestMeta) -> User:
    ensure_unique_identity(db, username=data.username, email=data.email)
    user = User(
        full_name=data.full_name,
        username=data.username,
        email=data.email,
        role_id=_role(db, data.role).id,
        is_active=data.is_active,
        password_hash=hash_password(data.password),
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    if data.role == ROLE_BARBERO:
        _link_barber(db, user, data.barber_id)
    elif data.role == ROLE_CLIENTE:
        _link_client(db, user, data.phone)
    audit(db, actor.id, "USUARIO_CREADO", "user", user.id, _snapshot(user), meta)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, data: UserUpdateIn, actor: User, meta: RequestMeta) -> User:
    """Edición completa (0024827 / 0022630). Conserva relaciones históricas: citas, ventas y auditoría
    siguen apuntando al mismo usuario/cliente/barbero aunque cambie el rol."""
    user = get_user(db, user_id)
    before = _snapshot(user)
    role_changed = data.role != user.role_code

    if user.is_protected and (data.role != ROLE_ADMIN or not data.is_active):
        raise BadRequest("La cuenta de administrador principal no puede cambiar de rol ni desactivarse.")
    if user.id == actor.id and (role_changed or not data.is_active):
        raise BadRequest("No puedes cambiar tu propio rol ni desactivar tu propia cuenta.")
    if user.role_code == ROLE_ADMIN and user.is_active and (role_changed or not data.is_active):
        if _active_admin_count(db, exclude_id=user.id) == 0:
            raise BadRequest("Debe existir al menos un administrador activo.")
    if data.role != ROLE_BARBERO and data.barber_id:
        raise BadRequest("Solo las cuentas de barbero se vinculan a un barbero.", fields={"barber_id": "No aplica para este rol."})

    ensure_unique_identity(
        db,
        username=data.username,
        email=data.email,
        exclude_user_id=user.id,
    )
    user.full_name = data.full_name
    user.username = data.username
    user.email = data.email
    if role_changed:
        if user.role_code == ROLE_BARBERO:
            _unlink_barber(db, user)
        if user.role_code == ROLE_CLIENTE:
            _unlink_client(db, user)
        user.role_id = _role(db, data.role).id
        db.flush()
        db.refresh(user)

    if data.role == ROLE_BARBERO:
        _link_barber(db, user, data.barber_id or (user.barber.id if user.barber else None))
    elif data.role == ROLE_CLIENTE:
        _link_client(db, user, data.phone)

    if user.is_active and not data.is_active:
        revoke_all_sessions(db, user.id)
    user.is_active = data.is_active
    db.flush()
    db.refresh(user)
    changes = diff(before, _snapshot(user))
    if changes:
        action = "USUARIO_ROL_CAMBIADO" if "role" in changes else "USUARIO_EDITADO"
        audit(db, actor.id, action, "user", user.id, changes, meta)
    db.commit()
    db.refresh(user)
    return user


def set_user_status(db: Session, user_id: int, is_active: bool, actor: User, meta: RequestMeta) -> User:
    user = get_user(db, user_id)
    if user.is_active == is_active:
        return user
    if not is_active:
        if user.is_protected:
            raise BadRequest("La cuenta de administrador principal no se puede desactivar.")
        if user.id == actor.id:
            raise BadRequest("No puedes desactivar tu propia cuenta.")
        if user.role_code == ROLE_ADMIN and _active_admin_count(db, exclude_id=user.id) == 0:
            raise BadRequest("Debe existir al menos un administrador activo.")
        revoke_all_sessions(db, user.id)
    user.is_active = is_active
    audit(db, actor.id, "USUARIO_ACTIVADO" if is_active else "USUARIO_DESACTIVADO", "user", user.id, None, meta)
    db.commit()
    db.refresh(user)
    return user


def admin_set_password(db: Session, user_id: int, password: str, actor: User, meta: RequestMeta) -> None:
    user = get_user(db, user_id)
    if user.is_protected and actor.id != user.id:
        raise BadRequest("Solo el administrador principal puede cambiar su propia contraseña.")
    user.password_hash = hash_password(password)
    user.password_changed_at = datetime.now(UTC)
    revoke_all_sessions(db, user.id)
    audit(db, actor.id, "USUARIO_CONTRASENA_RESTABLECIDA", "user", user.id, None, meta)
    db.commit()
