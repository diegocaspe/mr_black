import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.validators import FieldErrors

logger = logging.getLogger("mrblack")

GENERIC_SAVE_ERROR = "No se pudo guardar la información. Inténtelo nuevamente."
GENERIC_ERROR = "Ocurrió un error inesperado. Inténtelo nuevamente."
SERVER_BUSY = "El servidor está atendiendo muchas solicitudes. Inténtalo nuevamente en unos segundos."


class AppError(Exception):
    """Error de negocio con mensaje apto para mostrar al usuario."""

    def __init__(self, status_code: int, code: str, message: str, fields: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or {}


class NotFound(AppError):
    def __init__(self, message: str = "El recurso solicitado no existe."):
        super().__init__(404, "not_found", message)


class Forbidden(AppError):
    def __init__(self, message: str = "No tienes permisos para realizar esta acción."):
        super().__init__(403, "forbidden", message)


class Unauthorized(AppError):
    def __init__(self, message: str = "Tu sesión no es válida o expiró. Inicia sesión nuevamente."):
        super().__init__(401, "unauthorized", message)


class Conflict(AppError):
    def __init__(self, message: str, code: str = "conflict", fields: dict | None = None):
        super().__init__(409, code, message, fields)


class BadRequest(AppError):
    def __init__(self, message: str, code: str = "bad_request", fields: dict | None = None):
        super().__init__(400, code, message, fields)


def _payload(code: str, message: str, fields: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "fields": fields or {}}}


def _clean_validation_message(msg: str) -> str:
    # Pydantic antepone "Value error, " a los ValueError de nuestros validadores.
    for prefix in ("Value error, ", "Assertion failed, "):
        if msg.startswith(prefix):
            return msg[len(prefix):]
    translations = {
        "Field required": "Este campo es obligatorio.",
        "Input should be a valid integer": "Debe ser un número entero.",
        "Input should be a valid number": "Debe ser un número válido.",
        "Input should be a valid date": "Fecha inválida.",
        "Input should be a valid string": "Debe ser un texto.",
        "Input should be a valid boolean": "Debe ser verdadero o falso.",
    }
    for en, es in translations.items():
        if msg.startswith(en):
            return es
    if "valid email" in msg:
        return "Ingresa un correo electrónico válido."
    if msg.startswith("Input should be greater than or equal to"):
        return "El valor es menor al mínimo permitido."
    if msg.startswith("Input should be less than or equal to"):
        return "El valor es mayor al máximo permitido."
    if msg.startswith("Input should be greater than"):
        return "El valor debe ser mayor."
    if msg.startswith("String should have at most"):
        return "El texto es demasiado largo."
    if msg.startswith("String should have at least"):
        return "El texto es demasiado corto."
    if msg.startswith("Input should be"):
        return "Valor no permitido."
    return msg


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_payload(exc.code, exc.message, exc.fields))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for err in exc.errors():
            original = (err.get("ctx") or {}).get("error")
            if isinstance(original, FieldErrors):
                for key, msg in original.fields.items():
                    fields.setdefault(key, msg)
                continue
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            key = ".".join(loc) or "_"
            fields.setdefault(key, _clean_validation_message(err.get("msg", "Valor inválido.")))
        first = next(iter(fields.values()), "Datos inválidos.")
        message = first if len(fields) == 1 else "Revisa los campos marcados."
        return JSONResponse(status_code=422, content=_payload("validation_error", message, fields))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        messages = {404: "Recurso no encontrado.", 405: "Método no permitido.", 401: "No autenticado."}
        detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload("http_error", messages.get(exc.status_code, detail or GENERIC_ERROR)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError):
        logger.warning("IntegrityError en %s %s: %s", request.method, request.url.path, exc.orig)
        return JSONResponse(status_code=409, content=_payload("integrity_error", GENERIC_SAVE_ERROR))

    @app.exception_handler(SQLAlchemyTimeoutError)
    async def pool_timeout_handler(request: Request, _: SQLAlchemyTimeoutError):
        # Todas las conexiones a la BD están ocupadas: se responde rápido para que el cliente reintente.
        logger.warning("Pool de conexiones agotado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=503, content=_payload("server_busy", SERVER_BUSY), headers={"Retry-After": "5"})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=_payload("server_error", GENERIC_ERROR))
