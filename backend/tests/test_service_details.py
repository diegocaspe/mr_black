"""Ficha del servicio: contenido (en qué consiste, qué incluye, oferta) y fotos, editables por el personal."""

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
CONTENT = {
    "details": "Lavado, corte a tijera o máquina según tu estilo y acabado con producto.",
    "includes": ["Lavado", "Asesoría de estilo", "Acabado con cera"],
    "offer": "10 % de descuento los martes",
}


def upload(api, service_id, data, ctype="image/png"):
    return api.c.post(f"/api/services/{service_id}/images", content=data, headers={**api._h(), "Content-Type": ctype})


def test_public_detail_has_empty_content_by_default(anon):
    s = anon.get("/api/services/1").json()
    assert s["name"] == "Corte" and s["details"] is None and s["includes"] == [] and s["offer"] is None and s["images"] == []


def test_caja_and_admin_edit_content(caja, admin, anon):
    r = caja.patch("/api/services/1/content", CONTENT)
    assert r.status_code == 200, r.text
    assert r.json()["includes"] == CONTENT["includes"]
    pub = anon.get("/api/services/1").json()
    assert pub["details"] == CONTENT["details"] and pub["offer"] == CONTENT["offer"]
    listed = next(s for s in anon.get("/api/services").json() if s["id"] == 1)
    assert listed["offer"] == CONTENT["offer"]
    r = admin.patch("/api/services/1/content", {"details": None, "includes": [], "offer": None})
    assert r.status_code == 200 and r.json()["includes"] == [] and r.json()["offer"] is None


def test_content_does_not_change_price_or_duration(caja, anon):
    before = anon.get("/api/services/1").json()
    caja.patch("/api/services/1/content", CONTENT)
    after = anon.get("/api/services/1").json()
    assert (after["price"], after["duration_minutes"], after["name"]) == (before["price"], before["duration_minutes"], before["name"])
    assert caja.patch("/api/services/1/content", {**CONTENT, "price": "1.00"}).status_code == 422


def test_caja_still_cannot_edit_price(caja):
    body = {"name": "Corte", "description": None, "price": "1.00", "duration_minutes": 45, "icon": "fa-scissors", "is_active": True}
    assert caja.put("/api/services/1", body).status_code == 403


def test_includes_cleaned_and_validated(caja):
    r = caja.patch("/api/services/1/content", {"includes": ["  Lavado ", "lavado", "", "Toalla caliente"]})
    assert r.status_code == 200 and r.json()["includes"] == ["Lavado", "Toalla caliente"]
    assert caja.patch("/api/services/1/content", {"includes": ["x" * 81]}).status_code == 422
    assert caja.patch("/api/services/1/content", {"includes": ["a"]}).status_code == 422
    assert caja.patch("/api/services/1/content", {"includes": [f"Item {i}" for i in range(11)]}).status_code == 422
    assert caja.patch("/api/services/1/content", {"offer": "x" * 121}).status_code == 422
    assert caja.patch("/api/services/1/content", {"details": "x" * 1001}).status_code == 422


def test_clients_and_barbers_cannot_edit(cliente, barbero, anon):
    for api in (cliente, barbero):
        assert api.patch("/api/services/1/content", CONTENT).status_code == 403
        assert upload(api, 1, PNG).status_code == 403
    assert anon.patch("/api/services/1/content", CONTENT).status_code == 401
    assert upload(anon, 1, PNG).status_code == 401


def test_service_gallery(caja, anon):
    a = upload(caja, 2, PNG).json()["images"][0]["id"]
    r = upload(caja, 2, PNG)
    assert r.status_code == 201
    b = r.json()["images"][1]["id"]
    assert r.json()["images"][0]["url"] == f"/api/service-images/{a}"
    img = anon.get(f"/api/service-images/{a}")
    assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
    r = caja.put("/api/services/2/images/order", {"image_ids": [b, a]})
    assert [i["id"] for i in r.json()["images"]] == [b, a]
    assert caja.delete(f"/api/services/1/images/{a}").status_code == 404  # foto de otro servicio
    assert [i["id"] for i in caja.delete(f"/api/services/2/images/{a}").json()["images"]] == [b]
    assert upload(caja, 2, b"<svg/>").json()["error"]["code"] == "image_type"


def test_inactive_service_hidden_from_public_but_visible_to_staff(admin, caja, anon):
    s = anon.get("/api/services/4").json()
    body = {k: s[k] for k in ("name", "description", "price", "duration_minutes", "icon")}
    assert admin.put("/api/services/4", {**body, "is_active": False}).status_code == 200
    assert anon.get("/api/services/4").status_code == 404
    assert caja.get("/api/services/4").status_code == 200


def test_barbers_keep_light_service_payload(caja, anon):
    caja.patch("/api/services/1/content", CONTENT)
    barber = anon.get("/api/barbers").json()[0]
    svc = next(s for s in barber["services"] if s["id"] == 1)
    assert "details" not in svc and "images" not in svc
