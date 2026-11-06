from datetime import datetime
from typing import Literal

from pydantic import field_validator, model_validator

from app.core.validators import FieldErrors, Password, PersonName, Phone, Username
from app.schemas.auth import Email
from app.schemas.common import InputModel, ORMModel

RoleCode = Literal["ADMIN", "CAJA", "BARBERO", "CLIENTE"]


class UserCreateIn(InputModel):
    full_name: PersonName
    username: Username
    email: Email | None = None
    role: RoleCode
    is_active: bool = True  # 0024830: el estado inicial se elige al crear (activo por defecto)
    password: Password
    password_confirm: str
    barber_id: int | None = None  # vincular a un perfil de barbero existente
    phone: Phone | None = None  # obligatorio para rol CLIENTE

    @model_validator(mode="after")
    def check(self):
        if self.password != self.password_confirm:
            raise FieldErrors({"password_confirm": "Las contraseñas no coinciden."})
        if self.role == "CLIENTE" and not self.phone:
            raise FieldErrors({"phone": "El teléfono es obligatorio para cuentas de cliente."})
        if self.role != "BARBERO" and self.barber_id:
            raise FieldErrors({"barber_id": "Solo las cuentas de barbero se vinculan a un barbero."})
        if self.username in self.password.lower():
            raise FieldErrors({"password": "La contraseña no debe contener el nombre de usuario."})
        return self


class UserUpdateIn(InputModel):
    full_name: PersonName
    username: Username
    email: Email | None = None
    role: RoleCode
    is_active: bool
    barber_id: int | None = None
    phone: Phone | None = None


class UserStatusIn(InputModel):
    is_active: bool


class AdminPasswordIn(InputModel):
    password: Password
    password_confirm: str

    @model_validator(mode="after")
    def check(self):
        if self.password != self.password_confirm:
            raise FieldErrors({"password_confirm": "Las contraseñas no coinciden."})
        return self


class UserOut(ORMModel):
    id: int
    username: str
    full_name: str
    email: str | None
    role: str
    is_active: bool
    is_protected: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    barber_id: int | None = None
    client_id: int | None = None
    phone: str | None = None

    @field_validator("role", mode="before")
    @classmethod
    def role_code(cls, v):
        return getattr(v, "code", v)
