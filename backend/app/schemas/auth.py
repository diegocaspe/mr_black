from typing import Annotated

from pydantic import AfterValidator, EmailStr, Field, field_validator, model_validator

from app.core.validators import FieldErrors, Password, PersonName, Phone
from app.schemas.common import InputModel, ORMModel


def _lower(v: str) -> str:
    return v.strip().lower()


Email = Annotated[EmailStr, AfterValidator(_lower), Field(max_length=120)]


class LoginIn(InputModel):
    identifier: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def required_fields(self):
        missing = {}
        if not self.identifier.strip():
            missing["identifier"] = "Ingresa tu usuario, teléfono o correo."
        if not self.password:
            missing["password"] = "Ingresa tu contraseña."
        if missing:
            raise FieldErrors(missing)
        return self


class RegisterIn(InputModel):
    full_name: PersonName
    phone: Phone
    email: Email
    password: Password
    password_confirm: str = Field(max_length=128)

    @model_validator(mode="after")
    def check(self):
        if self.password != self.password_confirm:
            raise FieldErrors({"password_confirm": "Las contraseñas no coinciden."})
        if self.phone in self.password:
            raise FieldErrors({"password": "La contraseña no debe contener tu número de teléfono."})
        return self


class ForgotPasswordIn(InputModel):
    email: Email


class ResetPasswordIn(InputModel):
    token: str = Field(min_length=20, max_length=200)
    password: Password
    password_confirm: str = Field(max_length=128)

    @model_validator(mode="after")
    def check(self):
        if self.password != self.password_confirm:
            raise FieldErrors({"password_confirm": "Las contraseñas no coinciden."})
        return self


class ChangePasswordIn(InputModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password
    new_password_confirm: str = Field(max_length=128)

    @model_validator(mode="after")
    def check(self):
        if self.new_password != self.new_password_confirm:
            raise FieldErrors({"new_password_confirm": "Las contraseñas no coinciden."})
        if self.new_password == self.current_password:
            raise FieldErrors({"new_password": "La nueva contraseña debe ser distinta a la actual."})
        return self


class ProfileUpdateIn(InputModel):
    full_name: PersonName
    phone: Phone | None = None
    email: Email | None = None


class ClientMini(ORMModel):
    id: int
    phone: str
    email: str | None


class MeOut(ORMModel):
    id: int
    username: str
    full_name: str
    email: str | None
    role: str
    client: ClientMini | None = None
    barber_id: int | None = None

    @field_validator("role", mode="before")
    @classmethod
    def role_code(cls, v):
        return getattr(v, "code", v)
