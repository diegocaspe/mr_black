"""Autorización por rol aplicada en el servidor (nunca solo ocultando botones)."""

import pytest


@pytest.mark.parametrize("url", ["/api/auth/me", "/api/users", "/api/clients", "/api/cart", "/api/reports/dashboard",
                                 "/api/appointments", "/api/sales", "/api/audit", "/api/notifications"])
def test_protected_endpoints_require_login(anon, url):
    assert anon.get(url).status_code == 401


def test_cliente_cannot_escalate_to_admin(cliente):
    me = cliente.get("/api/auth/me").json()
    r = cliente.put(f"/api/users/{me['id']}", {"full_name": "Carlos Mendoza", "username": "987654321", "role": "ADMIN", "is_active": True})
    assert r.status_code == 403
    r = cliente.put("/api/auth/me", {"full_name": "Carlos Mendoza", "role": "ADMIN"})
    assert r.status_code == 422  # campo no permitido
    assert cliente.get("/api/auth/me").json()["role"] == "CLIENTE"


@pytest.mark.parametrize("method,url", [
    ("get", "/api/users"), ("get", "/api/audit"), ("get", "/api/reports/finance?date_from=2026-01-01&date_to=2026-01-31"),
    ("post", "/api/admin/products"), ("post", "/api/barbers"), ("post", "/api/services"), ("put", "/api/settings/business"),
    ("post", "/api/inventory/movements"),
])
def test_caja_cannot_use_admin_endpoints(caja, method, url):
    assert getattr(caja, method)(url).status_code == 403


@pytest.mark.parametrize("method,url", [
    ("get", "/api/clients"), ("post", "/api/sales"), ("get", "/api/admin/products"), ("get", "/api/reports/dashboard"),
    ("post", "/api/appointments/1/charge"),
])
def test_cliente_cannot_use_staff_endpoints(cliente, method, url):
    r = getattr(cliente, method)(url)
    assert r.status_code == 403


def test_barbero_cannot_register_or_cancel(barbero):
    assert barbero.post("/api/appointments", {"service_id": 1, "barber_id": 1, "start_at": "2030-01-01T10:00:00-05:00", "client_id": 1}).status_code == 403
    assert barbero.get("/api/cart").status_code == 403


def test_client_cannot_see_other_clients_data(cliente, cliente2):
    andrea_appt = cliente2.get("/api/appointments").json()["items"][0]["id"]
    assert cliente.get(f"/api/appointments/{andrea_appt}").status_code == 404
    assert cliente.post(f"/api/appointments/{andrea_appt}/cancel", {}).status_code == 404
    sale = cliente2.get("/api/sales").json()["items"][0]["id"]
    assert cliente.get(f"/api/sales/{sale}").status_code == 404
    assert cliente.get(f"/api/sales/{sale}/receipt.pdf").status_code == 404


def test_barber_sees_only_own_agenda(barbero):
    items = barbero.get("/api/appointments", params={"page_size": 100}).json()["items"]
    assert items and all(a["barber"]["id"] == 1 for a in items)


def test_unknown_fields_rejected_mass_assignment(admin):
    r = admin.post("/api/clients", {"full_name": "Pedro Ruiz", "phone": "955444333", "is_active": False, "id": 99, "user_id": 1})
    assert r.status_code == 422


def test_errors_do_not_leak_internals(admin):
    r = admin.get("/api/users/999999")
    assert r.status_code == 404
    assert "Traceback" not in r.text and "sqlalchemy" not in r.text.lower()


def test_security_headers(anon):
    r = anon.get("/api/services")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
