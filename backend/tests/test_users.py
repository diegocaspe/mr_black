"""Gestión de usuarios (0024830, 0024827, 0022630, 0024805)."""

from tests.conftest import Api

NEW = {"full_name": "Rosa Linares", "username": "rosa.caja", "email": "rosa@example.com", "role": "CAJA",
       "password": "CajaRosa2026", "password_confirm": "CajaRosa2026"}


def test_create_user_active_by_default(admin):
    r = admin.post("/api/users", NEW)
    assert r.status_code == 201, r.text
    assert r.json()["is_active"] is True


def test_create_user_inactive_initial_state(admin, anon):
    """0024830: el estado inicial elegido (inactivo) se guarda."""
    r = admin.post("/api/users", {**NEW, "is_active": False})
    assert r.status_code == 201 and r.json()["is_active"] is False
    assert admin.get(f"/api/users/{r.json()['id']}").json()["is_active"] is False
    assert anon.post("/api/auth/login", {"identifier": "rosa.caja", "password": "CajaRosa2026"}).status_code == 401


def test_create_user_validations(admin):
    r = admin.post("/api/users", {**NEW, "username": "ro sa", "full_name": "R0sa", "password": "abc", "password_confirm": "abc"})
    fields = r.json()["error"]["fields"]
    assert r.status_code == 422 and {"username", "full_name", "password"} <= set(fields)
    dup = admin.post("/api/users", {**NEW, "username": "admin"})
    assert dup.status_code == 409 and "username" in dup.json()["error"]["fields"]


def test_edit_user_data_and_role(admin, as_user):
    """0024827 / 0022630: editar nombre, usuario y rol (Caja → Barbero) sin recrear la cuenta."""
    r = admin.put("/api/users/2", {"full_name": "Encargado General", "username": "caja.general", "email": "caja@example.com",
                                   "role": "BARBERO", "is_active": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "BARBERO" and body["username"] == "caja.general" and body["full_name"] == "Encargado General"
    assert body["barber_id"] is not None  # se creó/vinculó su perfil de barbero
    # El perfil nuevo no tiene servicios todavía: no se publica hasta que el admin los configure.
    assert body["barber_id"] not in [b["id"] for b in Api().get("/api/barbers").json()]
    u = as_user("caja.general")
    assert u.get("/api/auth/me").json()["role"] == "BARBERO"
    assert u.get("/api/users").status_code == 403


def test_role_change_preserves_history(admin, as_user):
    before = as_user("barbero1").get("/api/appointments", params={"page_size": 100}).json()["total"]
    r = admin.put("/api/users/3", {"full_name": "Diego C", "username": "barbero1", "email": "barbero1@example.com",
                                   "role": "CAJA", "is_active": True})
    assert r.status_code == 200
    # El perfil de barbero y sus citas siguen existiendo; se puede volver a vincular.
    r = admin.put("/api/users/3", {"full_name": "Diego C", "username": "barbero1", "email": "barbero1@example.com",
                                   "role": "BARBERO", "is_active": True, "barber_id": 1})
    assert r.status_code == 200 and r.json()["barber_id"] == 1
    assert as_user("barbero1").get("/api/appointments", params={"page_size": 100}).json()["total"] == before


def test_protected_admin_and_self_rules(admin):
    r = admin.put("/api/users/1", {"full_name": "Administrador Principal", "username": "admin", "email": "admin@example.com",
                                   "role": "CAJA", "is_active": True})
    assert r.status_code == 400
    assert admin.patch("/api/users/1/status", {"is_active": False}).status_code == 400


def test_deactivate_revokes_sessions(admin, caja):
    assert caja.get("/api/auth/me").status_code == 200
    assert admin.patch("/api/users/2/status", {"is_active": False}).json()["is_active"] is False
    assert caja.get("/api/auth/me").status_code == 401
    assert admin.patch("/api/users/2/status", {"is_active": True}).json()["is_active"] is True
    Api().login("caja")


def test_admin_reset_password(admin):
    r = admin.post("/api/users/2/password", {"password": "NuevaCaja2026", "password_confirm": "NuevaCaja2026"})
    assert r.status_code == 200
    Api().login("caja", "NuevaCaja2026")


def test_audit_records_user_changes(admin):
    admin.post("/api/users", NEW)
    actions = [a["action"] for a in admin.get("/api/audit", params={"entity": "user"}).json()["items"]]
    assert "USUARIO_CREADO" in actions


def test_create_client_account_requires_phone(admin):
    r = admin.post("/api/users", {**NEW, "role": "CLIENTE", "username": "nuevo.cliente"})
    assert r.status_code == 422 and "phone" in r.json()["error"]["fields"]
    r = admin.post("/api/users", {**NEW, "role": "CLIENTE", "username": "nuevo.cliente", "phone": "955 111 222"})
    assert r.status_code == 201 and r.json()["phone"] == "955111222"
