"""Productos, baja lógica, stock mínimo, alertas e inventario
(0024828, 0022634, 0024798, 0024818, 0024820)."""

import pytest

NEW = {"name": "Pomada Clásica", "description": "Brillo medio", "category_id": 3, "price": "22.50",
       "image_url": None, "icon": "fa-jar", "min_stock": 3, "is_active": True, "initial_stock": 10}


@pytest.mark.parametrize("name", ["$$AAAA", "Gel<b>", "Pomada@2026", "ab"])
def test_product_name_rejected(admin, name):
    r = admin.post("/api/admin/products", {**NEW, "name": name})
    assert r.status_code == 422 and "name" in r.json()["error"]["fields"]


@pytest.mark.parametrize("price", ["0.000000000001", "0", "0.00", "0.05", "12.345", "-1"])
def test_product_price_rejected(admin, price):
    """0022634: precios que se verían como S/ 0.00 o con más de 2 decimales se rechazan."""
    r = admin.post("/api/admin/products", {**NEW, "price": price})
    assert r.status_code == 422 and "price" in r.json()["error"]["fields"]


def test_product_price_float_tiny_rejected(admin):
    assert admin.post("/api/admin/products", {**NEW, "price": 1e-12}).status_code == 422


def test_create_product_and_movement(admin, anon):
    r = admin.post("/api/admin/products", NEW)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["price"] == "22.50" and p["stock"] == 10
    assert p["id"] in [x["id"] for x in anon.get("/api/products").json()]
    mv = admin.get("/api/inventory/movements", params={"product_id": p["id"]}).json()
    assert mv[0]["movement_type"] == "ENTRADA" and mv[0]["quantity"] == 10


def test_duplicate_name_case_insensitive(admin):
    assert admin.post("/api/admin/products", {**NEW, "name": "gel mr black"}).status_code == 409


def test_deactivate_product_really_persists(admin, anon, cliente):
    """0024798: 'Dar de baja' cambia el estado, lo oculta de la tienda y permite reactivar."""
    r = admin.patch("/api/admin/products/1/status", {"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert admin.get("/api/admin/products/1").json()["is_active"] is False
    assert 1 not in [p["id"] for p in anon.get("/api/products").json()]
    assert anon.get("/api/products/1").status_code == 404
    assert cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1}).status_code == 404
    r = admin.patch("/api/admin/products/1/status", {"is_active": True})
    assert r.json()["is_active"] is True
    assert 1 in [p["id"] for p in anon.get("/api/products").json()]


def test_deactivated_product_in_cart_blocks_checkout(admin, cliente):
    assert cliente.post("/api/cart/items", {"product_id": 2, "quantity": 1}).status_code == 200
    admin.patch("/api/admin/products/2/status", {"is_active": False})
    cart = cliente.get("/api/cart").json()
    assert cart["can_checkout"] is False and cart["issues"]
    r = cliente.post("/api/cart/checkout", {"payment_method": "LOCAL"})
    assert r.status_code == 409


def test_min_stock_change_recalculates_alerts_immediately(admin, caja):
    """0024818: al subir el mínimo de 3 a 5, un producto con stock 4 pasa a alerta en el acto."""
    admin.post("/api/inventory/movements", {"product_id": 5, "movement_type": "AJUSTE", "quantity": 4, "reason": "Conteo"})
    alerts = {p["id"] for p in admin.get("/api/inventory/alerts").json()}
    assert 5 in alerts  # stock 4 <= min 4
    admin.put("/api/admin/products/5", {"name": "Bálsamo para Barba", "description": None, "category_id": 2, "price": "30.00",
                                         "image_url": None, "icon": "fa-jar", "min_stock": 2, "is_active": True})
    assert 5 not in {p["id"] for p in admin.get("/api/inventory/alerts").json()}
    r = admin.post("/api/inventory/min-stock", {"min_stock": 5})
    assert r.status_code == 200
    alerts = {p["id"] for p in caja.get("/api/inventory/alerts").json()}
    assert 5 in alerts and 3 in alerts and 1 not in alerts
    dash = {p["id"] for p in admin.get("/api/reports/dashboard").json()["low_stock"]}
    assert 5 in dash
    notif = [n["type"] for n in admin.get("/api/notifications").json()]
    assert "STOCK_BAJO" in notif


def test_inventory_movements_rules(admin, caja):
    assert admin.post("/api/inventory/movements", {"product_id": 3, "movement_type": "ENTRADA", "quantity": 8}).json()["stock_after"] == 10
    r = admin.post("/api/inventory/movements", {"product_id": 3, "movement_type": "SALIDA", "quantity": 11, "reason": "Merma"})
    assert r.status_code == 409 and "quedan 10" in r.json()["error"]["message"]
    assert admin.post("/api/inventory/movements", {"product_id": 3, "movement_type": "SALIDA", "quantity": 1}).status_code == 422  # motivo obligatorio
    assert admin.post("/api/inventory/movements", {"product_id": 3, "movement_type": "AJUSTE", "quantity": 7, "reason": "Conteo"}).json()["stock_after"] == 7
    assert caja.post("/api/inventory/movements", {"product_id": 3, "movement_type": "ENTRADA", "quantity": 1}).status_code == 403
    history = admin.get("/api/inventory/movements", params={"product_id": 3}).json()
    assert [m["movement_type"] for m in history[:2]] == ["AJUSTE", "ENTRADA"]  # más reciente primero
    assert history[0]["stock_before"] == 10 and history[0]["stock_after"] == 7 and history[0]["user"]["id"] == 1
    assert admin.get("/api/inventory/summary").status_code == 200


def test_product_update_does_not_change_stock_directly(admin):
    r = admin.put("/api/admin/products/1", {"name": "Gel Mr Black", "category_id": 3, "price": "19.90", "min_stock": 3,
                                            "is_active": True, "icon": "fa-bottle-droplet", "stock": 999})
    assert r.status_code == 422  # el stock solo cambia mediante movimientos
