import logging
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import RequestMeta
from app.core.errors import AppError, BadRequest, Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    needs_rehash,
    new_reset_token,
    new_session_id,
    verify_password,
)
from app.core.validators import normalize_phone
from app.integrations.email import OutgoingEmail, render_layout
from app.models.client import Client
from app.models.user import ROLE_CLIENTE, LoginAttempt, PasswordResetToken, Role, User, UserSession
from app.schemas.auth import RegisterIn
from app.services.audit_service import audit
from app.services.notification_service import notify, send_email_task

logger = logging.getLogger("mrblack.auth")

INVALID_CREDENTIALS = "Usuario o contraseña incorrectos."
TOO_MANY_ATTEMPTS = "Demasiados intentos fallidos. Espera unos minutos e inténtalo nuevamente."


def find_user_by_identifier(db: Session, identifier: str) -> User | None:
    ident = identifier.strip().lower()
    conditions = [User.username == ident, User.email == ident]
    try:
        phone = normalize_phone(identifier)
        conditions.append(User.id.in_(select(Client.user_id).where(Client.phone == phone)))
    except ValueError:
        pass
    return db.scalars(select(User).where(or_(*conditions))).first()


def _check_rate_limit(db: Session, identifier: str, ip: str | None) -> None:
    s = get_settings()
    since = datetime.now(UTC) - timedelta(minutes=s.login_window_minutes)
    by_user = db.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.identifier == identifier, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since
        )
    )
    by_ip = 0
    if ip:
        by_ip = db.scalar(
            select(func.count()).select_from(LoginAttempt).where(
                LoginAttempt.ip_address == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since
            )
        )
    if by_user >= s.login_max_failures_per_user or by_ip >= s.login_max_failures_per_ip:
        raise AppError(429, "too_many_attempts", TOO_MANY_ATTEMPTS)


def create_session(db: Session, user: User, meta: RequestMeta) -> tuple[str, datetime]:
    sid = new_session_id()
    token, expires = create_access_token(user.id, sid, user.role_code)
    db.add(UserSession(id=sid, user_id=user.id, expires_at=expires, ip_address=meta.ip, user_agent=meta.user_agent))
    return token, expires


def login(db: Session, identifier: str, password: str, meta: RequestMeta) -> tuple[User, str, datetime]:
    ident = identifier.strip().lower()[:120]
    _check_rate_limit(db, ident, meta.ip)
    user = find_user_by_identifier(db, identifier)
    password_hash = user.password_hash if user else None
    # Aún no se escribió nada: se devuelve la conexión al pool mientras se calcula el hash (la parte
    # más lenta del login), para que muchos inicios de sesión simultáneos no agoten las conexiones.
    db.rollback()
    ok = verify_password(password, password_hash)
    if not ok or not user or not user.is_active:
        db.add(LoginAttempt(identifier=ident, ip_address=meta.ip, success=False))
        audit(db, user.id if user else None, "LOGIN_FALLIDO", "auth", user.id if user else None,
              {"identifier": ident, "motivo": "cuenta inactiva" if (ok and user and not user.is_active) else "credenciales"}, meta)
        db.commit()
        # Mismo mensaje para usuario inexistente, contraseña incorrecta o cuenta inactiva (no enumerar).
        raise Unauthorized(INVALID_CREDENTIALS)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    db.add(LoginAttempt(identifier=ident, ip_address=meta.ip, success=True))
    token, expires = create_session(db, user, meta)
    audit(db, user.id, "LOGIN", "auth", user.id, None, meta)
    db.commit()
    return user, token, expires


def logout(db: Session, user: User, session_id: str | None, meta: RequestMeta) -> None:
    if session_id:
        db.execute(update(UserSession).where(UserSession.id == session_id).values(revoked_at=datetime.now(UTC)))
    audit(db, user.id, "LOGOUT", "auth", user.id, None, meta)
    db.commit()


def revoke_all_sessions(db: Session, user_id: int, except_session: str | None = None) -> None:
    stmt = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session:
        stmt = stmt.where(UserSession.id != except_session)
    db.execute(stmt.values(revoked_at=datetime.now(UTC)))


def ensure_unique_identity(db: Session, *, username: str | None = None, email: str | None = None,
                           phone: str | None = None, exclude_user_id: int | None = None,
                           exclude_client_id: int | None = None) -> None:
    errors: dict[str, str] = {}
    if username:
        q = select(User.id).where(User.username == username)
        if exclude_user_id:
            q = q.where(User.id != exclude_user_id)
        if db.scalar(q):
            errors["username"] = "Ese nombre de usuario ya está en uso."
    if email:
        q = select(User.id).where(User.email == email)
        if exclude_user_id:
            q = q.where(User.id != exclude_user_id)
        if db.scalar(q):
            errors["email"] = "Ese correo ya está registrado."
    if phone:
        q = select(Client.id).where(Client.phone == phone)
        if exclude_client_id:
            q = q.where(Client.id != exclude_client_id)
        if db.scalar(q):
            errors["phone"] = "Ya existe un cliente con ese teléfono."
    if errors:
        raise Conflict(next(iter(errors.values())), code="duplicate", fields=errors)


def register_client(db: Session, data: RegisterIn, meta: RequestMeta, tasks: BackgroundTasks) -> tuple[User, str, datetime]:
    # Un cliente registrado en caja (sin cuenta) puede reclamar su ficha con el mismo teléfono.
    existing_client = db.scalars(select(Client).where(Client.phone == data.phone)).first()
    if existing_client and existing_client.user_id is not None:
        raise Conflict("Ya existe una cuenta con ese teléfono.", code="duplicate",
                       fields={"phone": "Ya existe una cuenta con ese teléfono."})
    ensure_unique_identity(db, username=data.phone, email=data.email)

    role = db.scalars(select(Role).where(Role.code == ROLE_CLIENTE)).one()
    user = User(
        username=data.phone,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role_id=role.id,
        is_active=True,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    if existing_client:
        existing_client.user_id = user.id
        existing_client.full_name = data.full_name
        existing_client.email = data.email
        client = existing_client
    else:
        client = Client(user_id=user.id, full_name=data.full_name, phone=data.phone, email=data.email)
        db.add(client)
    db.flush()
    audit(db, user.id, "REGISTRO_CLIENTE", "user", user.id, {"client_id": client.id}, meta)
    notify(db, user.id, "BIENVENIDA", "¡Bienvenido a Mr Black!", "Tu cuenta fue creada. Ya puedes reservar tu cita y comprar en la tienda.", "#/reservar")
    token, expires = create_session(db, user, meta)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    html, text = render_layout(
        "¡Bienvenido a Mr Black!",
        f"Hola {data.full_name}, tu cuenta fue creada correctamente. Ya puedes reservar tus citas y comprar productos.",
        [("Usuario", data.phone), ("Correo", data.email)],
        ("Reservar una cita", f"{get_settings().frontend_url}/index.html#agendar"),
    )
    tasks.add_task(send_email_task, OutgoingEmail(data.email, "Bienvenido a Mr Black", html, text, "bienvenida"))
    return user, token, expires


def request_password_reset(db: Session, email: str, meta: RequestMeta, tasks: BackgroundTasks) -> None:
    """Siempre responde igual (no revela si el correo existe). Limita a 3 solicitudes/15 min por usuario."""
    s = get_settings()
    user = db.scalars(select(User).where(User.email == email)).first()
    if not user or not user.is_active:
        audit(db, None, "RECUPERACION_SOLICITADA", "auth", None, {"email": email, "resultado": "sin cuenta activa"}, meta)
        db.commit()
        return
    since = datetime.now(UTC) - timedelta(minutes=15)
    recent = db.scalar(
        select(func.count()).select_from(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.created_at >= since
        )
    )
    if recent >= 3:
        audit(db, user.id, "RECUPERACION_LIMITADA", "auth", user.id, None, meta)
        db.commit()
        return
    # Invalida tokens anteriores sin usar.
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=datetime.now(UTC))
    )
    token, token_hash = new_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=s.password_reset_expire_minutes),
            ip_address=meta.ip,
        )
    )
    audit(db, user.id, "RECUPERACION_SOLICITADA", "auth", user.id, None, meta)
    db.commit()

    link = f"{s.frontend_url}/restablecer.html?token={token}"
    html, text = render_layout(
        "Restablece tu contraseña",
        f"Hola {user.full_name}, recibimos una solicitud para restablecer tu contraseña. "
        f"El enlace es válido durante {s.password_reset_expire_minutes} minutos y solo puede usarse una vez.",
        None,
        ("Crear nueva contraseña", link),
        "Si no solicitaste este cambio, ignora este correo: tu contraseña actual sigue siendo válida.",
    )
    tasks.add_task(send_email_task, OutgoingEmail(user.email, "Recupera tu contraseña · Mr Black", html, text, "recuperacion"))


def _valid_reset_token(db: Session, token: str) -> PasswordResetToken:
    row = db.scalars(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)).with_for_update()
    ).first()
    if not row or row.used_at is not None or row.expires_at <= datetime.now(UTC):
        raise BadRequest("El enlace de recuperación no es válido o ya expiró. Solicita uno nuevo.", code="invalid_token")
    return row


def check_reset_token(db: Session, token: str) -> None:
    _valid_reset_token(db, token)
    db.rollback()


def reset_password(db: Session, token: str, new_password: str, meta: RequestMeta) -> None:
    row = _valid_reset_token(db, token)
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise BadRequest("El enlace de recuperación no es válido o ya expiró. Solicita uno nuevo.", code="invalid_token")
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(UTC)
    row.used_at = datetime.now(UTC)
    revoke_all_sessions(db, user.id)
    audit(db, user.id, "CONTRASENA_RESTABLECIDA", "user", user.id, None, meta)
    notify(db, user.id, "SEGURIDAD", "Contraseña actualizada", "Tu contraseña fue restablecida. Si no fuiste tú, contacta a la barbería.")
    db.commit()


def change_password(db: Session, user: User, current: str, new: str, session_id: str | None, meta: RequestMeta) -> None:
    if not verify_password(current, user.password_hash):
        raise BadRequest("La contraseña actual es incorrecta.", code="wrong_password",
                         fields={"current_password": "La contraseña actual es incorrecta."})
    user.password_hash = hash_password(new)
    user.password_changed_at = datetime.now(UTC)
    revoke_all_sessions(db, user.id, except_session=session_id)
    audit(db, user.id, "CONTRASENA_CAMBIADA", "user", user.id, None, meta)
    db.commit()
