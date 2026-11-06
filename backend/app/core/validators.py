"""Reglas de validación centralizadas.

Única fuente de verdad para nombres, teléfonos, contraseñas, precios, ratings, URLs y
fechas. Los esquemas Pydantic las usan como tipos anotados; el frontend replica las
mismas expresiones en `frontend/js/validators.js` solo para dar feedback inmediato.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated
from urllib.parse import urlparse

from pydantic import AfterValidator, BeforeValidator

LETTERS = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"

PERSON_NAME_RE = re.compile(rf"^[{LETTERS}]+(?: [{LETTERS}]+)*$")
PERSON_NAME_MIN, PERSON_NAME_MAX = 2, 60

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,30}$")
PHONE_RE = re.compile(r"^9\d{8}$")
PHONE_ALLOWED_RE = re.compile(r"^[\d\s\-().+]+$")

PRODUCT_NAME_RE = re.compile(rf"^[{LETTERS}0-9]+(?:[ .\-][{LETTERS}0-9]+)*\.?$")
PRODUCT_NAME_MIN, PRODUCT_NAME_MAX = 3, 60

CATEGORY_NAME_RE = re.compile(rf"^[{LETTERS}0-9]+(?: [{LETTERS}0-9]+)*$")
SERVICE_NAME_RE = re.compile(rf"^[{LETTERS}0-9]+(?:(?: |\s?\+\s?|\s?-\s?)[{LETTERS}0-9]+)*$")

PASSWORD_MIN, PASSWORD_MAX = 8, 128
COMMON_PASSWORDS = {
    "password1", "password123", "contraseña1", "contrasena1", "12345678a", "a12345678",
    "qwerty123", "abc12345", "abcd1234", "admin123", "admin1234", "barberia1", "mrblack1",
    "iloveyou1", "123456789a", "1234567a", "passw0rd", "welcome1",
}

PRICE_MIN = Decimal("0.10")
PRICE_MAX = Decimal("99999.99")
RATING_MIN, RATING_MAX = Decimal("0.0"), Decimal("5.0")
URL_MAX = 500
TEXT_MAX = 500
REPORT_DATE_MIN = date(2000, 1, 1)
REPORT_DATE_MAX = date(2099, 12, 31)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FieldErrors(ValueError):
    """Error de validación entre campos. El manejador 422 lo expande a mensajes por campo."""

    def __init__(self, fields: dict[str, str]):
        self.fields = fields
        super().__init__(next(iter(fields.values())))


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value or "")).strip()


def validate_person_name(value: str) -> str:
    v = collapse_spaces(value)
    if not v:
        raise ValueError("El nombre es obligatorio.")
    if len(v) < PERSON_NAME_MIN or len(v) > PERSON_NAME_MAX:
        raise ValueError(f"El nombre debe tener entre {PERSON_NAME_MIN} y {PERSON_NAME_MAX} caracteres.")
    if not PERSON_NAME_RE.match(v):
        raise ValueError("El nombre solo puede contener letras (incluidas tildes y ñ) y espacios.")
    return v


def validate_username(value: str) -> str:
    v = (value or "").strip().lower()
    if not USERNAME_RE.match(v):
        raise ValueError("Usuario inválido: 3 a 30 caracteres con letras, números, punto, guion o guion bajo, sin espacios.")
    return v


def normalize_phone(value: str) -> str:
    """Acepta 987654321, 987 654 321, 987-654-321, +51 987 654 321; devuelve 987654321."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("El teléfono es obligatorio.")
    if not PHONE_ALLOWED_RE.match(raw):
        raise ValueError("El teléfono solo puede contener dígitos, espacios o guiones.")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("51"):
        digits = digits[2:]
    if not PHONE_RE.match(digits):
        raise ValueError("El teléfono debe tener 9 dígitos y empezar con 9 (formato 9XXXXXXXX).")
    return digits


def password_strength(password: str) -> int:
    """Puntaje 0–4 usado también por el indicador de fortaleza del frontend."""
    score = 0
    if len(password) >= PASSWORD_MIN:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r"[a-z]", password) and re.search(r"[A-Z]", password):
        score += 1
    if re.search(r"[^A-Za-z0-9]", password):
        score += 1
    return score


def validate_password(value: str) -> str:
    v = value or ""
    if len(v) < PASSWORD_MIN:
        raise ValueError(f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres.")
    if len(v) > PASSWORD_MAX:
        raise ValueError(f"La contraseña no puede superar {PASSWORD_MAX} caracteres.")
    if not re.search(rf"[{LETTERS}]", v):
        raise ValueError("La contraseña debe incluir al menos una letra.")
    if not re.search(r"\d", v):
        raise ValueError("La contraseña debe incluir al menos un número.")
    if v.strip() != v:
        raise ValueError("La contraseña no puede empezar ni terminar con espacios.")
    if v.lower() in COMMON_PASSWORDS:
        raise ValueError("La contraseña es demasiado común. Elige una más segura.")
    return v


def validate_product_name(value: str) -> str:
    v = collapse_spaces(value)
    if len(v) < PRODUCT_NAME_MIN or len(v) > PRODUCT_NAME_MAX:
        raise ValueError(f"El nombre debe tener entre {PRODUCT_NAME_MIN} y {PRODUCT_NAME_MAX} caracteres.")
    if not PRODUCT_NAME_RE.match(v) or not re.search(rf"[{LETTERS}]", v):
        raise ValueError("El nombre solo puede contener letras, números, espacios, guion y punto.")
    return v


def validate_category_name(value: str) -> str:
    v = collapse_spaces(value)
    if len(v) < 3 or len(v) > 40 or not CATEGORY_NAME_RE.match(v):
        raise ValueError("La categoría debe tener entre 3 y 40 caracteres (letras, números y espacios).")
    return v


def validate_service_name(value: str) -> str:
    v = collapse_spaces(value)
    if len(v) < 3 or len(v) > 50 or not SERVICE_NAME_RE.match(v) or not re.search(rf"[{LETTERS}]", v):
        raise ValueError("El nombre del servicio debe tener entre 3 y 50 caracteres (letras, números, espacios, + y -).")
    return v


def _to_decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Debe ser un número.")
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Debe ser un número válido.") from None
    if not d.is_finite():
        raise ValueError("Debe ser un número válido.")
    return d


def validate_price(value) -> Decimal:
    d = _to_decimal(value)
    if d.as_tuple().exponent < -2 and d != d.quantize(Decimal("0.01")):
        raise ValueError("El precio admite como máximo 2 decimales.")
    if d < PRICE_MIN:
        raise ValueError(f"El precio mínimo es S/ {PRICE_MIN}.")
    if d > PRICE_MAX:
        raise ValueError(f"El precio máximo es S/ {PRICE_MAX}.")
    return d.quantize(Decimal("0.01"))


def validate_rating(value) -> Decimal:
    d = _to_decimal(value)
    if d.as_tuple().exponent < -1 and d != d.quantize(Decimal("0.1")):
        raise ValueError("La valoración admite un solo decimal (ej. 4.5).")
    if d < RATING_MIN or d > RATING_MAX:
        raise ValueError("La valoración debe estar entre 0.0 y 5.0.")
    return d.quantize(Decimal("0.1"))


def validate_image_url(value: str | None) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if len(v) > URL_MAX:
        raise ValueError(f"La URL no puede superar {URL_MAX} caracteres.")
    if v.startswith("/assets/"):
        if not re.match(r"^/assets/[A-Za-z0-9._/-]+$", v) or ".." in v:
            raise ValueError("Ruta de imagen inválida.")
        return v
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or re.search(r"[\s<>\"']", v):
        raise ValueError("Ingresa una URL de imagen válida que empiece con http:// o https://.")
    host = parsed.hostname or ""
    if "." not in host and host != "localhost":
        raise ValueError("Ingresa una URL de imagen válida con un dominio completo.")
    return v


def validate_text(value: str | None, max_len: int = TEXT_MAX) -> str | None:
    if value is None:
        return None
    v = _CONTROL_CHARS.sub("", unicodedata.normalize("NFC", value)).strip()
    if len(v) > max_len:
        raise ValueError(f"El texto no puede superar {max_len} caracteres.")
    return v or None


def validate_report_date(value: date) -> date:
    if value < REPORT_DATE_MIN or value > REPORT_DATE_MAX:
        raise ValueError("La fecha debe estar entre 01/01/2000 y 31/12/2099.")
    return value


def _strip_str(v):
    return v.strip() if isinstance(v, str) else v


PersonName = Annotated[str, AfterValidator(validate_person_name)]
Username = Annotated[str, AfterValidator(validate_username)]
Phone = Annotated[str, AfterValidator(normalize_phone)]
Password = Annotated[str, AfterValidator(validate_password)]
ProductName = Annotated[str, AfterValidator(validate_product_name)]
CategoryName = Annotated[str, AfterValidator(validate_category_name)]
ServiceName = Annotated[str, AfterValidator(validate_service_name)]
Price = Annotated[Decimal, BeforeValidator(validate_price)]
Rating = Annotated[Decimal, BeforeValidator(validate_rating)]
ImageUrl = Annotated[str | None, BeforeValidator(validate_image_url)]
ShortText = Annotated[str | None, BeforeValidator(_strip_str), AfterValidator(validate_text)]
ReportDate = Annotated[date, AfterValidator(validate_report_date)]
