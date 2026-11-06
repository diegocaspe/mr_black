"""Autenticación, registro, sesiones y recuperación (0024799, 0024819, 0024792, 0024803)."""

import os
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Client, User
from tests.conftest import PASSWORD, Api, first_receipt_token

FRONTEND = Path(os.environ.get("FRONTEND_DIR") or Path(__file__).resolve().parents[2] / "frontend")


def test_login_ok_sets_httponly_cookie(anon):
    r = anon.post("/api/auth/login", {"identifier": "admin", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"
    cookie = r.headers.get("set-cookie", "")
    assert "mb_session=" in cookie and "HttpOnly" in cookie
    assert "password" not in r.text and "password_hash" not in r.text
    assert anon.get("/api/auth/me").json()["username"] == "admin"


def test_session_endpoint_never_401(anon):
    r = anon.get("/api/auth/session")
    assert r.status_code == 200 and r.json() is None
    anon.login("caja")
    assert anon.get("/api/auth/session").json()["role"] == "CAJA"


def test_login_with_phone_in_any_format(anon):
    r = anon.post("/api/auth/login", {"identifier": "987 654 321", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "CLIENTE"


def test_login_wrong_password_generic_message(anon):
    r = anon.post("/api/auth/login", {"identifier": "admin", "password": "otra-clave-123"})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Usuario o contraseña incorrectos."
    r2 = anon.post("/api/auth/login", {"identifier": "no-existe", "password": "otra-clave-123"})
    assert r2.json()["error"]["message"] == r.json()["error"]["message"]  # no enumera usuarios


def test_login_empty_fields_returns_message_per_field(anon):
    """0024819: mensajes claros por campo cuando faltan datos."""
    r = anon.post("/api/auth/login", {"identifier": "", "password": ""})
    assert r.status_code == 422
    fields = r.json()["error"]["fields"]
    assert fields["identifier"] == "Ingresa tu usuario, teléfono o correo."
    assert fields["password"] == "Ingresa tu contraseña."


def test_login_requires_csrf(anon):
    r = anon.c.post("/api/auth/login", json={"identifier": "admin", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_inactive_user_cannot_login(admin, anon):
    assert admin.patch("/api/users/2/status", {"is_active": False}).status_code == 200
    r = anon.post("/api/auth/login", {"identifier": "caja", "password": PASSWORD})
    assert r.status_code == 401


def test_login_rate_limit(anon):
    for _ in range(5):
        anon.post("/api/auth/login", {"identifier": "caja", "password": "incorrecta-1"})
    r = anon.post("/api/auth/login", {"identifier": "caja", "password": PASSWORD})
    assert r.status_code == 429


def test_logout_revokes_session(cliente):
    assert cliente.get("/api/auth/me").status_code == 200
    token = cliente.c.cookies.get("mb_session")
    assert cliente.post("/api/auth/logout").status_code == 200
    other = Api()
    other.c.cookies.set("mb_session", token)
    assert other.get("/api/auth/me").status_code == 401  # el JWT robado ya no sirve


def test_passwords_are_hashed_with_argon2():
    db = SessionLocal()
    try:
        for u in db.scalars(select(User)).all():
            assert u.password_hash.startswith("$argon2id$")
            assert PASSWORD not in u.password_hash
    finally:
        db.close()


def test_login_page_has_no_demo_credentials():
    """0024799: ninguna credencial expuesta en la interfaz pública."""
    for page in ("login.html", "index.html", "registro.html"):
        content = (FRONTEND / page).read_text(encoding="utf-8").lower()
        assert "1234" not in content and "admin/" not in content and "demo:" not in content
        assert PASSWORD.lower() not in content


# ------------------------------------------------------------------ registro
VALID = {"full_name": "Mario Quispe", "phone": "912 345 678", "email": "mario@example.com",
         "password": "Corte2026seguro", "password_confirm": "Corte2026seguro"}


def test_register_normalizes_phone_and_logs_in(anon, outbox):
    r = anon.post("/api/auth/register", VALID)
    assert r.status_code == 201, r.text
    assert r.json()["client"]["phone"] == "912345678"  # 0024803: un solo formato almacenado
    assert anon.get("/api/auth/me").json()["role"] == "CLIENTE"
    assert any("Bienvenido" in e.subject for e in outbox)


def test_register_rejects_weak_password(anon):
    r = anon.post("/api/auth/register", {**VALID, "password": "1234", "password_confirm": "1234"})
    assert r.status_code == 422
    assert "password" in r.json()["error"]["fields"]


def test_register_rejects_invalid_name_and_phone(anon):
    r = anon.post("/api/auth/register", {**VALID, "full_name": "Mario$$ 123", "phone": "98765abc1"})
    fields = r.json()["error"]["fields"]
    assert r.status_code == 422 and "full_name" in fields and "phone" in fields


def test_register_password_mismatch(anon):
    r = anon.post("/api/auth/register", {**VALID, "password_confirm": "Otra2026clave"})
    assert r.json()["error"]["fields"]["password_confirm"] == "Las contraseñas no coinciden."


def test_register_duplicate_phone_in_other_format(anon):
    r = anon.post("/api/auth/register", {**VALID, "phone": "987-654-321", "email": "otro@example.com"})
    assert r.status_code == 409
    assert "phone" in r.json()["error"]["fields"]


def test_register_cannot_choose_role(anon):
    r = anon.post("/api/auth/register", {**VALID, "role": "ADMIN"})
    assert r.status_code == 422  # campos desconocidos rechazados (asignación masiva)


def test_register_claims_walk_in_client(anon):
    r = anon.post("/api/auth/register", {**VALID, "phone": "988111222", "email": "jose@example.com"})
    assert r.status_code == 201
    db = SessionLocal()
    try:
        c = db.scalars(select(Client).where(Client.phone == "988111222")).one()
        assert c.user_id is not None and c.id == 3  # conserva su historial previo
    finally:
        db.close()


# ------------------------------------------------------------------ recuperación de contraseña
def test_password_reset_full_flow(anon, outbox):
    r = anon.post("/api/auth/forgot-password", {"email": "carlos.mendoza@example.com"})
    assert r.status_code == 200
    token = first_receipt_token(outbox)
    assert PASSWORD not in outbox[-1].text  # nunca se envía la contraseña
    assert anon.get(f"/api/auth/reset-password/{token}").status_code == 200
    r = anon.post("/api/auth/reset-password", {"token": token, "password": "NuevaClave2026", "password_confirm": "NuevaClave2026"})
    assert r.status_code == 200
    # token invalidado tras el uso
    r = anon.post("/api/auth/reset-password", {"token": token, "password": "OtraClave2026x", "password_confirm": "OtraClave2026x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"
    assert Api().post("/api/auth/login", {"identifier": "987654321", "password": "NuevaClave2026"}).status_code == 200
    assert Api().post("/api/auth/login", {"identifier": "987654321", "password": PASSWORD}).status_code == 401


def test_forgot_password_unknown_email_same_response(anon, outbox):
    r = anon.post("/api/auth/forgot-password", {"email": "nadie@example.com"})
    assert r.status_code == 200 and not outbox


def test_reset_with_invalid_token(anon):
    r = anon.post("/api/auth/reset-password", {"token": "x" * 40, "password": "NuevaClave2026", "password_confirm": "NuevaClave2026"})
    assert r.status_code == 400


def test_change_password_requires_current_and_revokes_other_sessions(as_user):
    s1 = as_user("caja")
    s2 = as_user("caja")
    bad = s1.post("/api/auth/change-password", {"current_password": "incorrecta1", "new_password": "CajaNueva2026", "new_password_confirm": "CajaNueva2026"})
    assert bad.status_code == 400
    ok = s1.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "CajaNueva2026", "new_password_confirm": "CajaNueva2026"})
    assert ok.status_code == 200
    assert s1.get("/api/auth/me").status_code == 200
    assert s2.get("/api/auth/me").status_code == 401
