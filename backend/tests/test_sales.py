"""Carrito, stock, pagos simulados, ventas y comprobantes (0024820, 0024817, 0022634)."""

import threading

from sqlalchemy import text

from app.core.database import engine

CARD = {"card_number": "4242 4242 4242 4242", "card_holder": "Carlos Mendoza", "card_expiry": "12/39", "card_cvv": "123"}


def stock(admin, pid):
    return admin.get(f"/api/admin/products/{pid}").json()["stock"]


def test_cart_add_beyond_stock_shows_remaining(cliente):
    """0024820: 'Stock insuficiente: quedan X unidades' y nunca más que el stock."""
    r = cliente.post("/api/cart/items", {"product_id": 3, "quantity": 5})  # Cera Matte: stock 2
    assert r.status_code == 409
    assert r.json()["error"]["message"].startswith("Stock insuficiente: quedan 2 unidades")
    assert cliente.post("/api/cart/items", {"product_id": 3, "quantity": 2}).status_code == 200
    r = cliente.post("/api/cart/items", {"product_id": 3, "quantity": 1})
    assert r.status_code == 409 and "Ya tienes 2" in r.json()["error"]["message"]
    r = cliente.put("/api/cart/items/3", {"quantity": 3})
    assert r.status_code == 409 and r.json()["error"]["fields"]["quantity"] == "Máximo 2 unidades."


def test_cart_operations(cliente):
    c = cliente.post("/api/cart/items", {"product_id": 1, "quantity": 2}).json()
    assert c["item_count"] == 2 and c["total"] == "36.00"
    c = cliente.put("/api/cart/items/1", {"quantity": 3}).json()
    assert c["total"] == "54.00"
    c = cliente.post("/api/cart/items", {"product_id": 2, "quantity": 1}).json()
    assert c["total"] == "82.00" and len(c["items"]) == 2
    c = cliente.delete("/api/cart/items/2").json()
    assert len(c["items"]) == 1
    c = cliente.delete("/api/cart").json()
    assert c["items"] == [] and c["can_checkout"] is False
    assert cliente.put("/api/cart/items/1", {"quantity": 0}).status_code == 422


def test_cart_persists_server_side(cliente, as_user):
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 2})
    other_session = as_user("987654321")
    assert other_session.get("/api/cart").json()["item_count"] == 2


def test_checkout_online_card(cliente, admin, outbox):
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 2})
    cliente.post("/api/cart/items", {"product_id": 2, "quantity": 1})
    r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": CARD})
    assert r.status_code == 201, r.text
    sale = r.json()
    assert sale["status"] == "PAGADA" and sale["total"] == "64.00" and sale["receipt_code"].startswith("B001-")
    assert sale["payments"][0]["payer_detail"] == "Visa •••• 4242"
    assert "4242424242424242" not in r.text and "123" not in sale["payments"][0]["payer_detail"]
    assert stock(admin, 1) == 10 and stock(admin, 2) == 7  # stock descontado
    assert cliente.get("/api/cart").json()["items"] == []  # carrito vaciado
    pdf = cliente.get(f"/api/sales/{sale['id']}/receipt.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    mail = next(e for e in outbox if "Comprobante" in e.subject)
    assert mail.attachments and mail.attachments[0].content.startswith(b"%PDF")
    mv = admin.get("/api/inventory/movements", params={"product_id": 1, "movement_type": "VENTA"}).json()
    assert mv[0]["sale_id"] == sale["id"] and mv[0]["quantity"] == -2


def test_any_16_digit_card_is_accepted(cliente):
    """Pago simulado: sin Luhn ni números "de rechazo"; basta con 16 dígitos."""
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1})
    r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE",
                                            "payment": {**CARD, "card_number": "1234-5678 9012 0002"}})
    assert r.status_code == 201, r.text
    assert r.json()["payments"][0]["payer_detail"] == "Tarjeta •••• 0002"  # marca no reconocida


def test_mastercard_brand_is_recorded(cliente):
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1})
    r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": {**CARD, "card_number": "5500000000000004"}})
    assert r.status_code == 201 and r.json()["payments"][0]["payer_detail"] == "Mastercard •••• 0004"


def test_invalid_card_creates_nothing(cliente, admin):
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1})
    r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": {**CARD, "card_expiry": "01/20"}})
    assert r.status_code == 400 and r.json()["error"]["fields"]["payment.card_expiry"] == "La tarjeta está vencida."
    assert stock(admin, 1) == 12 and cliente.get("/api/cart").json()["item_count"] == 1
    assert cliente.get("/api/sales").json()["total"] == 2  # solo las ventas históricas del seed


def test_payment_validation_errors(cliente):
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1})
    for bad in ("1234", "4242 4242 4242 424", "4242 4242 4242 42424", "4242 4242 4242 424a"):
        r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": {**CARD, "card_number": bad}})
        assert r.status_code == 400 and "payment.card_number" in r.json()["error"]["fields"], bad
    for bad in ("12", "1234", "12a"):
        r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": {**CARD, "card_cvv": bad}})
        assert r.status_code in (400, 422), bad
        if r.status_code == 400:
            assert "payment.card_cvv" in r.json()["error"]["fields"], bad
    for bad in ("13/30", "00/30", "1230", "12-30"):
        r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": {**CARD, "card_expiry": bad}})
        assert r.status_code == 400 and "payment.card_expiry" in r.json()["error"]["fields"], bad
    r = cliente.post("/api/cart/checkout", {"payment_method": "ONLINE", "payment": {**CARD, "card_holder": None}})
    assert r.status_code == 400 and "payment.card_holder" in r.json()["error"]["fields"]
    r = cliente.post("/api/cart/checkout", {"payment_method": "YAPE", "payment": {"wallet_phone": "987654321", "approval_code": "12"}})
    assert r.status_code == 400 and "payment.approval_code" in r.json()["error"]["fields"]


def test_payment_methods_are_mutually_exclusive(cliente):
    """0024817: un único método por pago; no se aceptan varios a la vez."""
    cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1})
    r = cliente.post("/api/cart/checkout", {"payment_method": ["EFECTIVO", "YAPE", "PLIN"]})
    assert r.status_code == 422
    r = cliente.post("/api/cart/checkout", {"payment_method": "EFECTIVO"})
    assert r.status_code == 400  # efectivo es para caja; en línea se usa "Pago en local"
    methods = {m["code"]: m for m in cliente.get("/api/payments/methods").json()}
    assert set(methods) == {"ONLINE", "YAPE", "PLIN", "EFECTIVO", "LOCAL"} and methods["LOCAL"]["online_allowed"]


def test_yape_payment(cliente):
    cliente.post("/api/cart/items", {"product_id": 6, "quantity": 1})
    r = cliente.post("/api/cart/checkout", {"payment_method": "YAPE", "payment": {"wallet_phone": "987 654 321", "approval_code": "482913"}})
    assert r.status_code == 201 and r.json()["payments"][0]["payer_detail"].startswith("Yape 9")


def test_pay_at_store_flow(cliente, caja, admin):
    cliente.post("/api/cart/items", {"product_id": 6, "quantity": 3})
    sale = cliente.post("/api/cart/checkout", {"payment_method": "LOCAL"}).json()
    assert sale["status"] == "PENDIENTE_PAGO" and stock(admin, 6) == 17  # stock reservado
    assert any(n["type"] == "PEDIDO_PENDIENTE" for n in caja.get("/api/notifications").json())
    r = caja.post(f"/api/sales/{sale['id']}/confirm-payment", {"payment_method": "EFECTIVO", "payment": {"amount_received": "50.00"}})
    assert r.status_code == 200 and r.json()["status"] == "PAGADA" and r.json()["change_due"] == "5.00"
    assert caja.post(f"/api/sales/{sale['id']}/confirm-payment", {"payment_method": "EFECTIVO"}).status_code == 409


def test_cancel_pending_order_restores_stock(cliente, admin):
    cliente.post("/api/cart/items", {"product_id": 6, "quantity": 4})
    sale = cliente.post("/api/cart/checkout", {"payment_method": "LOCAL"}).json()
    assert stock(admin, 6) == 16
    r = cliente.post(f"/api/sales/{sale['id']}/cancel", {"reason": "Ya no lo necesito"})
    assert r.status_code == 200 and r.json()["status"] == "ANULADA"
    assert stock(admin, 6) == 20


def test_zero_total_impossible(cliente):
    """0022634: aunque alguien fuerce un precio ínfimo en la BD, el sistema no registra ventas de S/ 0.00."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE products DROP CONSTRAINT ck_products_price_min"))
        conn.execute(text("UPDATE products SET price = 0 WHERE id = 1"))
    try:
        assert cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1}).status_code == 409
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET price = 18 WHERE id = 1"))
            conn.execute(text("ALTER TABLE products ADD CONSTRAINT ck_products_price_min CHECK (price >= 0.10)"))


def test_empty_cart_checkout(cliente):
    r = cliente.post("/api/cart/checkout", {"payment_method": "LOCAL"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_cart"


def test_concurrent_checkouts_never_oversell(as_user, admin):
    """Dos clientes compran las 2 últimas unidades al mismo tiempo: una compra falla y el stock no queda negativo."""
    a, b = as_user("987654321"), as_user("999888777")
    for c in (a, b):
        assert c.post("/api/cart/items", {"product_id": 3, "quantity": 2}).status_code == 200
    barrier = threading.Barrier(2)
    codes = []

    def run(c):
        barrier.wait()
        codes.append(c.post("/api/cart/checkout", {"payment_method": "LOCAL"}).status_code)

    threads = [threading.Thread(target=run, args=(c,)) for c in (a, b)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [201, 409], codes
    assert stock(admin, 3) == 0


def test_counter_sale(caja, admin):
    r = caja.post("/api/sales", {"client_id": 3, "items": [{"product_id": 1, "quantity": 2}, {"product_id": 6, "quantity": 1}],
                                  "payment_method": "EFECTIVO", "payment": {"amount_received": "60"}})
    assert r.status_code == 201, r.text
    assert r.json()["total"] == "51.00" and r.json()["change_due"] == "9.00" and r.json()["channel"] == "MOSTRADOR"
    r = caja.post("/api/sales", {"items": [{"product_id": 3, "quantity": 3}], "payment_method": "EFECTIVO"})
    assert r.status_code == 409 and "quedan 2 unidades" in r.json()["error"]["message"]
    r = caja.post("/api/sales", {"items": [{"product_id": 1, "quantity": 1}], "payment_method": "LOCAL"})
    assert r.status_code == 400  # "pago en local" no aplica en mostrador


def test_charge_attended_appointment(caja, admin):
    unpaid = next(a for a in caja.get("/api/appointments", params={"status": "ATENDIDA"}).json()["items"] if a["can_charge"])
    r = caja.post(f"/api/appointments/{unpaid['id']}/charge", {"payment_method": "PLIN", "payment": {"wallet_phone": "988111222", "approval_code": "123456"}})
    assert r.status_code == 201
    assert r.json()["items"][0]["item_type"] == "SERVICIO" and r.json()["total"] == unpaid["price"]
    again = caja.post(f"/api/appointments/{unpaid['id']}/charge", {"payment_method": "EFECTIVO"})
    assert again.status_code == 409
    pending = caja.get("/api/appointments", params={"status": "PENDIENTE"}).json()["items"][0]
    assert caja.post(f"/api/appointments/{pending['id']}/charge", {"payment_method": "EFECTIVO"}).status_code == 409


def _unpaid_attended(api):
    return next(a for a in api.get("/api/appointments", params={"status": "ATENDIDA"}).json()["items"] if a["can_charge"])


def _receipts(sale_id):
    with engine.begin() as conn:
        return conn.execute(text("SELECT count(*) FROM receipts WHERE sale_id = :s"), {"s": sale_id}).scalar_one()


def test_charge_appointment_with_products_single_sale(caja, admin, outbox):
    unpaid = _unpaid_attended(caja)
    sales_before = caja.get("/api/sales").json()["total"]
    r = caja.post(f"/api/appointments/{unpaid['id']}/charge",
                  {"payment_method": "ONLINE", "payment": CARD, "items": [{"product_id": 1, "quantity": 2}]})
    assert r.status_code == 201, r.text
    sale = r.json()
    types = sorted(i["item_type"] for i in sale["items"])
    assert types == ["PRODUCTO", "SERVICIO"]
    assert float(sale["total"]) == float(unpaid["price"]) + 2 * 18.00  # servicio + 2 × S/ 18.00
    assert len(sale["payments"]) == 1 and float(sale["payments"][0]["amount"]) == float(sale["total"])
    assert caja.get("/api/sales").json()["total"] == sales_before + 1  # una sola venta
    assert _receipts(sale["id"]) == 1  # un solo comprobante
    assert stock(admin, 1) == 10  # stock descontado (12 → 10)
    mv = admin.get("/api/inventory/movements", params={"product_id": 1, "movement_type": "VENTA"}).json()
    assert mv[0]["sale_id"] == sale["id"] and mv[0]["quantity"] == -2
    assert caja.get(f"/api/appointments/{unpaid['id']}").json()["sale_id"] == sale["id"]
    mails = [e for e in outbox if "Comprobante" in e.subject]
    assert len(mails) == 1  # el comprobante se envía una sola vez
    assert "× 2" in mails[0].html and unpaid["service"]["name"] in mails[0].html  # con todas las líneas
    assert caja.get(f"/api/sales/{sale['id']}/receipt.pdf").content.startswith(b"%PDF")


def test_charge_appointment_without_stock_creates_nothing(caja, admin):
    unpaid = _unpaid_attended(caja)
    sales_before = caja.get("/api/sales").json()["total"]
    r = caja.post(f"/api/appointments/{unpaid['id']}/charge",
                  {"payment_method": "EFECTIVO", "items": [{"product_id": 1, "quantity": 1}, {"product_id": 3, "quantity": 3}]})
    assert r.status_code == 409 and "quedan 2 unidades" in r.json()["error"]["message"]
    assert caja.get("/api/sales").json()["total"] == sales_before  # no se creó la venta
    assert caja.get(f"/api/appointments/{unpaid['id']}").json()["sale_id"] is None  # la cita sigue por cobrar
    assert stock(admin, 1) == 12 and stock(admin, 3) == 2


def test_charge_appointment_rejects_duplicate_products(caja):
    unpaid = _unpaid_attended(caja)
    r = caja.post(f"/api/appointments/{unpaid['id']}/charge",
                  {"payment_method": "EFECTIVO", "items": [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}]})
    assert r.status_code == 422


def test_sales_filters(caja):
    assert all(s["channel"] == "ONLINE" for s in caja.get("/api/sales", params={"channel": "ONLINE"}).json()["items"])
    assert all(s["payment_method"] == "YAPE" for s in caja.get("/api/sales", params={"method": "YAPE"}).json()["items"])
    assert caja.get("/api/sales", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}).status_code == 400
