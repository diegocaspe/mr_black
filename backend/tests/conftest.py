"""Infraestructura de pruebas.

Las pruebas usan una base PostgreSQL real y aislada (TEST_DATABASE_URL) porque varias reglas
se garantizan en la base de datos (restricción de exclusión de citas, CHECK de stock, FOR UPDATE).
Antes de cada prueba se vacían las tablas y se cargan los datos de desarrollo (seed).
"""

import os
import re
from datetime import date, datetime, timedelta

from sqlalchemy.engine import make_url  # noqa: E402


def _safe_test_database_url() -> str:
    """Las pruebas ejecutan DROP SCHEMA public CASCADE: nunca deben tocar la base de la aplicación
    (p. ej. producción en Neon). Se exige una TEST_DATABASE_URL propia cuyo nombre contenga "test"."""
    from app.core.config import normalize_db_url

    test_url = normalize_db_url(os.environ.get("TEST_DATABASE_URL", "").strip())
    if not test_url:
        raise RuntimeError("Define TEST_DATABASE_URL (una base exclusiva para pruebas); las pruebas la vacían por completo.")
    app_url = normalize_db_url(os.environ.get("DATABASE_URL", "").strip())

    def target(url: str) -> tuple:
        u = make_url(url)
        return (u.host or "").lower(), u.port or 5432, u.database

    if app_url and target(app_url) == target(test_url):
        raise RuntimeError("TEST_DATABASE_URL apunta a la misma base que DATABASE_URL; las pruebas la borrarían.")
    if "test" not in (make_url(test_url).database or "").lower():
        raise RuntimeError('El nombre de la base de TEST_DATABASE_URL debe contener "test" (p. ej. mrblack_test).')
    return test_url


# La configuración debe apuntar a la BD de pruebas ANTES de importar la aplicación.
os.environ["DATABASE_URL"] = _safe_test_database_url()
os.environ["EMAIL_BACKEND"] = "console"
os.environ["SEED_DEFAULT_PASSWORD"] = "MrBlack.Dev-2026"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
os.environ["GOOGLE_REDIRECT_URI"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core.database import engine  # noqa: E402
from app.core.timeutils import today_local  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "MrBlack.Dev-2026"
CATALOG_TABLES = {"roles", "appointment_statuses", "payment_methods", "alembic_version"}


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    from alembic import command
    from alembic.config import Config

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def fresh_data(migrated_db):
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))]
        data_tables = [t for t in tables if t not in CATALOG_TABLES]
        conn.execute(text(f"TRUNCATE {', '.join(data_tables)} RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER SEQUENCE receipt_number_seq RESTART WITH 1"))
    from app.seed import run

    run()
    yield


@pytest.fixture
def outbox(monkeypatch):
    """Captura los correos enviados en lugar de usar SMTP."""
    sent = []

    class Collector:
        def send(self, email):
            sent.append(email)

    monkeypatch.setattr("app.services.notification_service.get_email_sender", lambda: Collector())
    return sent


class Api:
    """Cliente HTTP de pruebas que gestiona cookies y la cabecera CSRF como el frontend."""

    def __init__(self):
        self.c = TestClient(app, raise_server_exceptions=False)
        self.c.get("/api/auth/csrf")

    def _h(self):
        return {"X-CSRF-Token": self.c.cookies.get("mb_csrf", "")}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json if json is not None else {}, headers=self._h(), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json if json is not None else {}, headers=self._h(), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json if json is not None else {}, headers=self._h(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(), **kw)

    def login(self, identifier, password=PASSWORD):
        r = self.post("/api/auth/login", {"identifier": identifier, "password": password})
        assert r.status_code == 200, r.text
        return self


@pytest.fixture
def anon():
    return Api()


@pytest.fixture
def as_user():
    return lambda username, password=PASSWORD: Api().login(username, password)


@pytest.fixture
def admin(as_user):
    return as_user("admin")


@pytest.fixture
def caja(as_user):
    return as_user("caja")


@pytest.fixture
def barbero(as_user):
    return as_user("barbero1")  # Diego C (barber_id=1)


@pytest.fixture
def cliente(as_user):
    return as_user("987654321")  # Carlos Mendoza


@pytest.fixture
def cliente2(as_user):
    return as_user("999888777")  # Andrea Torres


# ------------------------------------------------------------------ utilidades de fechas
def future_weekday(weekday: int, min_days: int = 5) -> date:
    """Próxima fecha con el día de semana indicado (0=lunes) al menos `min_days` en el futuro."""
    d = today_local() + timedelta(days=min_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def slot(d: date, hhmm: str) -> str:
    return f"{d.isoformat()}T{hhmm}:00-05:00"


def first_receipt_token(outbox) -> str:
    for email in outbox:
        m = re.search(r"token=([A-Za-z0-9_\-]+)", email.text)
        if m:
            return m.group(1)
    raise AssertionError("No se envió el correo de recuperación")


__all__ = ["future_weekday", "slot", "first_receipt_token", "datetime"]
