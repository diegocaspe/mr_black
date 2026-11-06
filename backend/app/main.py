import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import appointments, auth, catalog, clients, products, reports, sales, system, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.security import CSRF_COOKIE, CSRF_HEADER, csrf_matches

settings = get_settings()
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Tareas de fondo ligadas a la vida del proceso (REMINDERS_ENABLED=true)."""
    task = None
    if settings.reminders_enabled:
        from app.services.reminder_service import reminder_loop

        task = asyncio.create_task(reminder_loop())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=lifespan,
    title="Mr Black Barbería API",
    version="1.0.0",
    description=(
        "API del sistema de gestión de Mr Black Barbería. La autenticación usa una cookie HttpOnly "
        "(`mb_session`) y las operaciones que modifican datos requieren la cabecera `X-CSRF-Token` "
        "con el valor de la cookie `mb_csrf`."
    ),
    # En producción no se publica la documentación interactiva de la API.
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None if settings.is_production else "/api/redoc",
    openapi_url=None if settings.is_production else "/api/openapi.json",
)
register_error_handlers(app)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER],
    )

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def csrf_and_headers(request: Request, call_next):
    # Protección CSRF de doble envío para toda operación que modifica datos.
    if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
        if not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "csrf", "message": "La sesión del formulario expiró. Recarga la página e inténtalo nuevamente.", "fields": {}}},
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/") and not request.url.path.startswith(("/api/docs", "/api/redoc")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


for r in (auth, users, clients, catalog, appointments, products, sales, reports, system):
    app.include_router(r.router)
