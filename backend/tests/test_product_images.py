"""Fotos de producto: subida por el personal (admin y caja), validación, galería pública y permisos."""

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def upload(api, product_id, data, ctype="image/png"):
    return api.c.post(f"/api/admin/products/{product_id}/images", content=data,
                      headers={**api._h(), "Content-Type": ctype})


def test_caja_uploads_and_public_sees_gallery(caja, anon):
    r = upload(caja, 1, PNG)
    assert r.status_code == 201, r.text
    images = r.json()["images"]
    assert len(images) == 1 and images[0]["url"] == f"/api/product-images/{images[0]['id']}"
    pub = anon.get("/api/products/1").json()
    assert [i["id"] for i in pub["images"]] == [images[0]["id"]]
    img = anon.get(images[0]["url"])
    assert img.status_code == 200 and img.content == PNG
    assert img.headers["content-type"] == "image/png"
    assert "immutable" in img.headers["cache-control"]


def test_admin_uploads_jpg_and_webp(admin):
    assert upload(admin, 1, JPG, "image/jpeg").status_code == 201
    r = upload(admin, 1, WEBP, "image/webp")
    assert r.status_code == 201
    assert len(r.json()["images"]) == 2


def test_type_detected_from_bytes_not_header(caja):
    r = upload(caja, 1, b"<svg onload=alert(1)></svg>", "image/png")
    assert r.status_code == 400 and r.json()["error"]["code"] == "image_type"
    r = upload(caja, 1, PNG, "text/html")
    assert r.status_code == 201
    assert caja.get(r.json()["images"][0]["url"]).headers["content-type"] == "image/png"


def test_empty_and_too_large_rejected(caja):
    assert upload(caja, 1, b"").status_code == 400
    r = upload(caja, 1, PNG + b"\x00" * 2_000_001)
    assert r.status_code == 400 and r.json()["error"]["code"] == "image_too_large"


def test_max_images_per_product(caja):
    for _ in range(8):
        assert upload(caja, 1, PNG).status_code == 201
    r = upload(caja, 1, PNG)
    assert r.status_code == 409 and r.json()["error"]["code"] == "image_limit"


def test_clients_and_barbers_cannot_manage_photos(cliente, barbero, anon, caja):
    assert upload(cliente, 1, PNG).status_code == 403
    assert upload(barbero, 1, PNG).status_code == 403
    assert upload(anon, 1, PNG).status_code == 401
    img_id = upload(caja, 1, PNG).json()["images"][0]["id"]
    assert cliente.delete(f"/api/admin/products/1/images/{img_id}").status_code == 403
    assert cliente.patch("/api/admin/products/1/image", {"image_url": None}).status_code == 403
    assert cliente.put("/api/admin/products/1/images/order", {"image_ids": [img_id]}).status_code == 403


def test_reorder_and_delete(caja, anon):
    a = upload(caja, 2, PNG).json()["images"][0]["id"]
    b = upload(caja, 2, JPG, "image/jpeg").json()["images"][1]["id"]
    r = caja.put("/api/admin/products/2/images/order", {"image_ids": [b, a]})
    assert r.status_code == 200 and [i["id"] for i in r.json()["images"]] == [b, a]
    assert caja.put("/api/admin/products/2/images/order", {"image_ids": [b]}).status_code == 400
    assert caja.put("/api/admin/products/2/images/order", {"image_ids": [b, b]}).status_code == 400
    assert caja.delete(f"/api/admin/products/1/images/{a}").status_code == 404  # foto de otro producto
    r = caja.delete(f"/api/admin/products/2/images/{b}")
    assert r.status_code == 200 and [i["id"] for i in r.json()["images"]] == [a]
    assert anon.get(f"/api/product-images/{b}").status_code == 404


def test_caja_sets_photo_url_but_not_other_fields(caja, admin):
    r = caja.patch("/api/admin/products/1/image", {"image_url": "https://example.com/gel.jpg"})
    assert r.status_code == 200 and r.json()["image_url"] == "https://example.com/gel.jpg"
    assert caja.patch("/api/admin/products/1/image", {"image_url": "javascript:alert(1)"}).status_code == 422
    assert caja.patch("/api/admin/products/1/image", {"image_url": None, "price": "1.00"}).status_code == 422
    p = admin.get("/api/admin/products/1").json()
    body = {k: p[k] for k in ("name", "description", "price", "image_url", "icon", "min_stock", "is_active")}
    assert caja.put("/api/admin/products/1", {**body, "category_id": p["category"]["id"]}).status_code == 403


def test_listing_includes_image_urls_without_bytes(caja, anon):
    upload(caja, 3, PNG)
    listing = anon.get("/api/products").json()
    p3 = next(p for p in listing if p["id"] == 3)
    assert len(p3["images"]) == 1 and "data" not in p3["images"][0]


def test_cart_thumbnail_uses_first_uploaded_photo(caja, admin, cliente):
    p = admin.get("/api/admin/products/1").json()
    assert caja.patch("/api/admin/products/1/image", {"image_url": None}).status_code == 200
    url = upload(caja, 1, PNG).json()["images"][0]["url"]
    cart = cliente.post("/api/cart/items", {"product_id": 1, "quantity": 1}).json()
    assert next(i for i in cart["items"] if i["product_id"] == 1)["image_url"] == url
    caja.patch("/api/admin/products/1/image", {"image_url": p["image_url"]})
