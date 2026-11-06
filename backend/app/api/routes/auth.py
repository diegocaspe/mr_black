from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import RequestMeta, get_current_user, get_optional_user, get_request_meta
from app.core.errors import BadRequest
from app.core.security import CSRF_COOKIE, SESSION_COOKIE, new_csrf_token
from app.models.user import ROLE_CLIENTE, User
from app.schemas.auth import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    MeOut,
    ProfileUpdateIn,
    RegisterIn,
    ResetPasswordIn,
)
from app.schemas.common import Message
from app.services import auth_service
from app.services.audit_service import audit, diff

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


def _set_session_cookie(response: Response, token: str, expires: datetime) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax", path="/",
        domain=s.cookie_domain, expires=expires,
    )
    # Rota el token CSRF en cada inicio de sesión.
    response.set_cookie(CSRF_COOKIE, new_csrf_token(), httponly=False, secure=s.cookie_secure, samesite="strict",
                        path="/", domain=s.cookie_domain)


def me_out(user: User) -> MeOut:
    out = MeOut.model_validate(user)
    out.barber_id = user.barber.id if user.barber else None
    return out


@router.get("/csrf", response_model=Message, summary="Obtiene/renueva la cookie CSRF")
def csrf(request: Request, response: Response):
    if not request.cookies.get(CSRF_COOKIE):
        s = get_settings()
        response.set_cookie(CSRF_COOKIE, new_csrf_token(), httponly=False, secure=s.cookie_secure,
                            samesite="strict", path="/", domain=s.cookie_domain)
    return Message(message="ok")


@router.post("/login", response_model=MeOut)
def login(data: LoginIn, response: Response, db: Session = Depends(get_db), meta: RequestMeta = Depends(get_request_meta)):
    user, token, expires = auth_service.login(db, data.identifier, data.password, meta)
    _set_session_cookie(response, token, expires)
    return me_out(user)


@router.post("/register", response_model=MeOut, status_code=201)
def register(data: RegisterIn, response: Response, tasks: BackgroundTasks, db: Session = Depends(get_db),
             meta: RequestMeta = Depends(get_request_meta)):
    user, token, expires = auth_service.register_client(db, data, meta, tasks)
    _set_session_cookie(response, token, expires)
    return me_out(user)


@router.post("/logout", response_model=Message)
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db),
           meta: RequestMeta = Depends(get_request_meta)):
    auth_service.logout(db, user, getattr(request.state, "session_id", None), meta)
    s = get_settings()
    response.delete_cookie(SESSION_COOKIE, path="/", domain=s.cookie_domain)
    return Message(message="Sesión cerrada.")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return me_out(user)


@router.get("/session", response_model=MeOut | None, summary="Usuario actual o null si no hay sesión (sin 401)")
def session(user: User | None = Depends(get_optional_user)):
    return me_out(user) if user else None


@router.put("/me", response_model=MeOut)
def update_me(data: ProfileUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
              meta: RequestMeta = Depends(get_request_meta)):
    before = {"full_name": user.full_name, "email": user.email, "phone": user.client.phone if user.client else None}
    email = data.email or user.email
    if user.role_code == ROLE_CLIENTE and not email:
        raise BadRequest("El correo es obligatorio para tu cuenta.", fields={"email": "Ingresa tu correo."})
    auth_service.ensure_unique_identity(db, email=email, exclude_user_id=user.id)
    if user.client and data.phone:
        auth_service.ensure_unique_identity(db, phone=data.phone, exclude_client_id=user.client.id)
    user.full_name = data.full_name
    user.email = email
    if user.client:
        user.client.full_name = data.full_name
        user.client.email = email
        if data.phone:
            user.client.phone = data.phone
    if user.barber:
        user.barber.full_name = data.full_name
    after = {"full_name": user.full_name, "email": user.email, "phone": user.client.phone if user.client else None}
    audit(db, user.id, "PERFIL_EDITADO", "user", user.id, diff(before, after), meta)
    db.commit()
    db.refresh(user)
    return me_out(user)


@router.post("/change-password", response_model=Message)
def change_password(data: ChangePasswordIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db), meta: RequestMeta = Depends(get_request_meta)):
    auth_service.change_password(db, user, data.current_password, data.new_password,
                                 getattr(request.state, "session_id", None), meta)
    return Message(message="Contraseña actualizada correctamente.")


@router.post("/forgot-password", response_model=Message)
def forgot_password(data: ForgotPasswordIn, tasks: BackgroundTasks, db: Session = Depends(get_db),
                    meta: RequestMeta = Depends(get_request_meta)):
    auth_service.request_password_reset(db, data.email, meta, tasks)
    return Message(message="Si el correo está registrado, recibirás un enlace para restablecer tu contraseña.")


@router.get("/reset-password/{token}", response_model=Message, summary="Valida un token de recuperación")
def check_reset(token: str, db: Session = Depends(get_db)):
    auth_service.check_reset_token(db, token)
    return Message(message="Token válido.")


@router.post("/reset-password", response_model=Message)
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db), meta: RequestMeta = Depends(get_request_meta)):
    auth_service.reset_password(db, data.token, data.password, meta)
    return Message(message="Tu contraseña fue actualizada. Ya puedes iniciar sesión.")
