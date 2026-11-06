"""Pruebas E2E en navegador real (Chromium headless) contra el stack levantado con Docker.

Uso (con `docker compose up -d` en ejecución):
    docker run --rm --network mrblack_default -v "$PWD/e2e:/e2e" -w /e2e \
        mcr.microsoft.com/playwright/python:v1.48.0-jammy \
        sh -c "pip install -q playwright==1.48.0 && python e2e_check.py"

Verifica flujos completos de cliente y administración, errores de JavaScript en consola,
comportamiento de modales (0022677), estrellas (0024822) y diseño responsive (0022604).
"""

import os
import random
import sys
from datetime import date, timedelta

from playwright.sync_api import Page, expect, sync_playwright

BASE = os.environ.get("BASE_URL", "http://frontend")
PASSWORD = os.environ.get("SEED_PASSWORD", "MrBlack.Dev-2026")
SHOTS = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SHOTS, exist_ok=True)

results: list[tuple[str, bool, str]] = []
LAURA = "Laura " + random.choice(["Campos", "Rojas", "Vega", "Salas", "Mora", "Ríos", "Paz", "Soto"]) + " " + random.choice(["Ugarte", "Núñez", "Ibarra", "León", "Cruz", "Prado"])


def check(name, fn):
    try:
        fn()
        results.append((name, True, ""))
        print(f"  OK   {name}")
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, str(exc).splitlines()[0][:300]))
        print(f"  FAIL {name}: {str(exc).splitlines()[0][:300]}")


def watch_errors(page: Page, bucket: list):
    page.on("pageerror", lambda e: bucket.append(f"pageerror: {e}"))
    page.on("console", lambda m: bucket.append(f"console: {m.text}") if m.type == "error" and "favicon" not in m.text else None)


def login(page: Page, user: str, password: str = PASSWORD):
    page.goto(f"{BASE}/login.html")
    page.fill("#identifier", user)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url("**/app.html**")
    page.wait_for_selector("#sidebar-nav a")


def future_weekday(weekday: int, min_days: int = 6) -> date:
    d = date.today() + timedelta(days=min_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---------------------------------------------------------------- público
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, locale="es-PE", timezone_id="America/Lima")
        page = ctx.new_page()
        errors: list[str] = []
        watch_errors(page, errors)
        print("Sitio público")

        def public_loads():
            page.goto(f"{BASE}/index.html")
            page.wait_for_selector("#services .service-card")
            page.wait_for_selector("#barbers .barber-card")
            page.wait_for_selector("#products .product-card")
            assert page.locator("#services .service-card").count() == 4
            page.screenshot(path=f"{SHOTS}/01-publico.png", full_page=True)

        check("Página pública carga servicios, barberos y productos desde la API", public_loads)

        def stars_exact():
            card = page.locator(".barber-card", has_text="Jhonatan Rojas")
            width = card.locator(".stars-fill").evaluate("e => e.style.width")
            assert width == "90%", width
            assert card.locator(".rating-label").inner_text() == "4.5"

        check("0024822 estrellas proporcionales (4.5 → 4 llenas + media)", stars_exact)

        def no_inactive_product():
            names = page.locator("#products h3").all_inner_texts()
            assert "Aceite para Barba" not in names, names

        check("0024798 producto dado de baja no aparece en la tienda", no_inactive_product)

        def login_no_credentials_and_field_errors():
            page.goto(f"{BASE}/login.html")
            body = page.content().lower()
            assert "1234" not in body and "demo" not in body
            page.click("button[type=submit]")
            expect(page.locator("#identifier-error")).to_have_text("Ingresa tu usuario, teléfono o correo.")
            expect(page.locator("#password-error")).to_have_text("Ingresa tu contraseña.")
            assert page.get_attribute("#identifier", "aria-invalid") == "true"
            page.fill("#identifier", "admin")
            page.fill("#password", "incorrecta123")
            page.click("button[type=submit]")
            expect(page.locator(".form-alert.err")).to_contain_text("Usuario o contraseña incorrectos")

        check("0024799/0024819 login sin credenciales visibles y con mensajes por campo", login_no_credentials_and_field_errors)

        # ---------------------------------------------------------------- registro + reserva + compra (cliente)
        print("Flujo cliente")
        phone = "9" + "".join(random.choice("0123456789") for _ in range(8))

        def register_validation():
            page.goto(f"{BASE}/registro.html")
            page.fill("#full_name", "Cliente 123$")
            page.fill("#phone", "98 76a")
            page.fill("#email", "no-es-correo")
            page.fill("#password", "1234")
            page.fill("#password_confirm", "1234")
            page.click("button[type=submit]")
            for f in ("full_name", "phone", "email", "password"):
                expect(page.locator(f"#{f}-error")).to_be_visible()

        check("0024792 registro valida nombre, teléfono y contraseña antes de guardar", register_validation)

        def register_ok():
            page.fill("#full_name", "Cliente Prueba")
            page.fill("#phone", f"{phone[:3]} {phone[3:6]}-{phone[6:]}")
            page.fill("#email", f"e2e{phone}@example.com")
            page.fill("#password", "Prueba2026segura")
            assert page.get_attribute("#strength", "data-score") in ("2", "3", "4")
            page.fill("#password_confirm", "Prueba2026segura")
            page.click("button[type=submit]")
            page.wait_for_url("**/app.html#/reservar")
            page.wait_for_selector("[data-service]")

        check("Registro de cliente con teléfono en formato libre", register_ok)

        def book_appointment():
            page.click("[data-service] >> text=Barba")
            page.click("[data-barber] >> text=Adriano Vargas")
            d = future_weekday(2)
            page.fill("#bk-date", d.isoformat())
            page.dispatch_event("#bk-date", "change")
            page.wait_for_selector(".slot:not([disabled])")
            assert page.locator(".slot >> text=13:00").count() == 0  # descanso no ofrecido
            page.locator(".slot:not([disabled])").first.click()
            page.click("[data-next]")
            page.click("[data-confirm]")
            expect(page.locator("#bk h3", has_text="¡Cita registrada!")).to_be_visible(timeout=10000)
            page.goto(f"{BASE}/app.html#/mis-citas")
            page.wait_for_selector(".appt-card")
            expect(page.locator(".appt-card").first).to_contain_text("Barba")
            page.screenshot(path=f"{SHOTS}/02-mis-citas.png", full_page=True)

        check("Reserva completa: servicio → barbero → fecha → horario → confirmación", book_appointment)

        def reschedule_and_cancel():
            page.locator(".appt-card [data-reschedule]").first.click()
            page.wait_for_selector(".modal .slot:not([disabled])")
            page.locator(".modal .slot:not([disabled])").nth(3).click()
            page.click(".modal [data-next]")
            page.click(".modal [data-confirm]")
            expect(page.locator(".toast.ok", has_text="reprogramada")).to_be_visible(timeout=10000)
            page.wait_for_selector(".appt-card [data-transition='CANCELADA']")
            page.locator(".appt-card [data-transition='CANCELADA']").first.click()
            page.click(".modal [data-ok]")
            expect(page.locator(".toast.ok", has_text="Cita cancelada")).to_be_visible(timeout=10000)

        check("Reprogramar y cancelar cita desde el panel del cliente", reschedule_and_cancel)

        def shop_and_checkout():
            page.goto(f"{BASE}/app.html#/tienda")
            page.wait_for_selector("[data-add]")
            card = page.locator(".product-card", has_text="Cera Matte")
            card.locator("[data-add]").click()
            expect(page.locator(".toast.ok", has_text="añadido")).to_be_visible()
            page.click("[data-cart]")
            page.wait_for_selector(".drawer .cart-line")
            inc = page.locator(".drawer [data-inc]").first
            # Cera Matte tiene stock bajo: "+" se deshabilita al llegar al máximo (0024820)
            for _ in range(5):
                if inc.is_disabled():
                    break
                inc.click()
                page.wait_for_timeout(300)
            assert inc.is_disabled()
            expect(page.locator(".drawer")).to_contain_text("Máximo disponible")
            page.click("[data-checkout]")
            page.wait_for_selector(".modal input[name=payment_method]")
            radios = page.locator(".modal input[name=payment_method]")
            assert radios.count() == 4  # online, yape, plin, pago en local
            yape = page.locator(".modal label.choice:has(input[value=YAPE])")
            yape.click()
            page.locator(".modal label.choice:has(input[value=PLIN])").click()
            checked = page.locator(".modal input[name=payment_method]:checked").count()
            assert checked == 1, "métodos de pago no excluyentes"  # 0024817
            assert page.locator(".modal label.choice:has(input[value=LOCAL])").count() == 1  # opción "Pago en local"
            yape.click()
            page.fill("[name='payment.wallet_phone']", phone)
            page.fill("[name='payment.approval_code']", "123456")
            page.click(".modal button[type=submit]")
            expect(page.locator(".modal-title", has_text="Gracias por tu compra")).to_be_visible(timeout=10000)
            page.screenshot(path=f"{SHOTS}/03-compra.png")
            page.click(".modal [data-close]")
            page.goto(f"{BASE}/app.html#/compras")
            page.wait_for_selector("table tbody tr")
            href = page.locator("a[href*='receipt.pdf']").first.get_attribute("href")
            resp = page.request.get(f"{BASE}{href}")
            assert resp.status == 200 and resp.body()[:4] == b"%PDF"

        check("0024817/0024820 carrito, stock máximo, pago excluyente y comprobante PDF", shop_and_checkout)
        client_errors = list(errors)
        ctx.close()

        # ---------------------------------------------------------------- administración
        print("Flujo administración")
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, locale="es-PE", timezone_id="America/Lima")
        page = ctx.new_page()
        errors = []
        watch_errors(page, errors)
        login(page, "admin")
        routes = ["dashboard", "citas", "caja", "ventas", "clientes", "inventario", "productos", "servicios", "barberos",
                  "finanzas", "usuarios", "auditoria", "configuracion", "notificaciones", "perfil"]

        def all_admin_routes():
            failed = []
            for r in routes:
                page.goto(f"{BASE}/app.html#/{r}")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(300)
                if page.locator("#content .loading").count() or page.locator("#content .empty .fa-triangle-exclamation").count():
                    failed.append(r)
            page.goto(f"{BASE}/app.html#/dashboard")
            page.wait_for_selector("#income-chart")
            page.wait_for_timeout(800)
            page.screenshot(path=f"{SHOTS}/04-dashboard.png", full_page=True)
            assert not failed, failed

        check("Todas las secciones de ADMIN cargan sin error", all_admin_routes)

        def modal_selection_does_not_close():
            page.goto(f"{BASE}/app.html#/usuarios")
            page.click("[data-new]")
            page.wait_for_selector(".modal #uf-name")
            page.fill("#uf-name", "Texto largo para seleccionar")
            box = page.locator("#uf-name").bounding_box()
            page.mouse.move(box["x"] + 5, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.mouse.move(5, 5, steps=8)  # arrastra fuera del modal, sobre el overlay
            page.mouse.up()
            page.wait_for_timeout(200)
            assert page.locator(".modal").count() == 1, "el modal se cerró al seleccionar texto"
            page.mouse.click(5, 5)  # clic válido sobre el overlay
            page.wait_for_timeout(200)
            assert page.locator(".modal").count() == 0
            page.click("[data-new]")
            page.wait_for_selector(".modal")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            assert page.locator(".modal").count() == 0

        check("0022677 el modal no se cierra al seleccionar texto y soltar fuera", modal_selection_does_not_close)

        def user_form_clean_and_initial_state():
            page.click("[data-new]")
            page.wait_for_selector(".modal #uf-name")
            page.fill("#uf-name", LAURA)
            page.fill("#uf-user", f"laura{random.randint(100, 999)}")
            page.locator(".modal label.switch").click()  # estado inicial: inactivo
            page.fill("#uf-pass", "Laura2026segura")
            page.fill("#uf-pass2", "Laura2026segura")
            page.click(".modal button[type=submit]")
            expect(page.locator(".toast.ok", has_text="inactiva")).to_be_visible(timeout=10000)
            page.click("[data-new]")
            page.wait_for_selector(".modal #uf-name")
            assert page.input_value("#uf-name") == "" and page.input_value("#uf-user") == ""
            assert page.is_checked(".modal input[name=is_active]")  # activo por defecto
            page.keyboard.press("Escape")

        check("0024805/0024830 formulario nuevo limpio y estado inicial elegible", user_form_clean_and_initial_state)

        def edit_user_role():
            row = page.locator("tbody tr", has_text=LAURA)
            row.locator("[data-edit]").click()
            page.wait_for_selector(".modal #uf-role")
            page.select_option("#uf-role", "BARBERO")
            page.click(".modal button[type=submit]")
            page.click(".modal [data-ok]")  # confirmar cambio de rol
            expect(page.locator(".toast.ok", has_text="Usuario actualizado")).to_be_visible(timeout=10000)
            expect(page.locator("tbody tr", has_text=LAURA)).to_contain_text("Barbero")

        check("0024827/0022630 edición de usuario y cambio de rol", edit_user_role)

        def barber_edit_persists():
            page.goto(f"{BASE}/app.html#/barberos")
            page.wait_for_selector("[data-edit]")
            page.locator("article", has_text="Luis Quispe").locator("[data-edit]").click()
            page.wait_for_selector(".modal #bf-rating")
            page.fill("#bf-rating", "4.8")
            page.fill("#bf-name", "Luis 999$$")
            page.click(".modal button[type=submit]")
            expect(page.locator("#bf-name-error")).to_be_visible()
            page.fill("#bf-name", "Luis Quispe")
            page.click(".modal button[type=submit]")
            expect(page.locator(".toast.ok", has_text="guardado")).to_be_visible(timeout=10000)
            page.reload()
            page.wait_for_selector("[data-edit]")
            expect(page.locator("article", has_text="Luis Quispe").locator(".rating-label")).to_have_text("4.8")

        check("0024802/0024794/0024829 edición de barbero valida y persiste tras recargar", barber_edit_persists)

        def product_validation_and_toggle():
            page.goto(f"{BASE}/app.html#/productos")
            page.wait_for_selector("[data-new]")
            page.click("[data-new]")
            page.fill("#pf-name", "$$AAAA")
            page.fill("#pf-price", "0.000000000001")
            page.click(".modal button[type=submit]")
            expect(page.locator("#pf-name-error")).to_be_visible()
            expect(page.locator("#pf-price-error")).to_be_visible()
            page.keyboard.press("Escape")
            row = page.locator("tbody tr", has_text="Peine de Madera")
            row.locator("[data-toggle]").click()
            page.click(".modal [data-ok]")
            expect(page.locator(".toast.ok", has_text="dado de baja")).to_be_visible(timeout=10000)
            expect(page.locator("tbody tr", has_text="Peine de Madera")).to_contain_text("Dado de baja")
            page.locator("tbody tr", has_text="Peine de Madera").locator("[data-toggle]").click()
            page.click(".modal [data-ok]")
            expect(page.locator("tbody tr", has_text="Peine de Madera").locator("[data-toggle]")).to_have_text("Dar de baja")

        check("0024828/0022634/0024798 validación de producto y baja/activación", product_validation_and_toggle)

        def finance_dates():
            page.goto(f"{BASE}/app.html#/finanzas")
            page.wait_for_selector("#ff-from")
            page.fill("#ff-from", "0001-01-01")
            page.click("#ff button[type=submit]")
            expect(page.locator("#ff-from-error")).to_be_visible()
            page.fill("#ff-from", "2026-12-31")
            page.fill("#ff-to", "2026-01-01")
            page.click("#ff button[type=submit]")
            expect(page.locator("#ff-to-error")).to_be_visible()

        check("0024831 finanzas rechaza años inválidos y rango invertido", finance_dates)

        def appointments_filters():
            page.goto(f"{BASE}/app.html#/citas")
            page.wait_for_selector("#appt-table tbody tr")
            page.select_option("#f-status", "ATENDIDA")
            page.wait_for_timeout(600)
            statuses = page.locator("#appt-table tbody td[data-label=Estado] .badge").all_inner_texts()
            assert statuses and all(s == "Atendida" for s in statuses), statuses
            page.click("[data-sort=cliente]")
            page.wait_for_timeout(600)
            assert page.locator("th[aria-sort] [data-sort=cliente]").count() == 1

        check("0022600 filtros y ordenamiento en la tabla de citas", appointments_filters)
        admin_errors = list(errors)
        ctx.close()

        # ---------------------------------------------------------------- responsive
        print("Responsive")
        for width, label in ((375, "movil"), (820, "tablet")):
            ctx = browser.new_context(viewport={"width": width, "height": 860}, locale="es-PE", timezone_id="America/Lima")
            page = ctx.new_page()
            login(page, "caja")

            def no_overflow(label=label, width=width, page=page):
                bad = []
                for r in ("citas", "caja", "ventas", "clientes", "inventario", "dashboard"):
                    page.goto(f"{BASE}/app.html#/{r}")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(300)
                    sw = page.evaluate("document.documentElement.scrollWidth")
                    if sw > width + 1:
                        bad.append(f"{r}:{sw}")
                page.goto(f"{BASE}/app.html#/citas")
                page.wait_for_selector("#appt-form")
                page.screenshot(path=f"{SHOTS}/05-citas-{label}.png", full_page=True)
                assert page.is_visible("#sidebar-open")
                page.click("#sidebar-open")
                expect(page.locator("#sidebar")).to_have_class("sidebar open")
                page.screenshot(path=f"{SHOTS}/06-menu-{label}.png")
                assert not bad, bad

            check(f"0022604 sin desbordes horizontales y menú colapsable ({width}px)", no_overflow)
            ctx.close()

        ctx = browser.new_context(viewport={"width": 375, "height": 860})
        page = ctx.new_page()

        def public_mobile():
            page.goto(f"{BASE}/index.html")
            page.wait_for_selector("#products .product-card")
            assert page.evaluate("document.documentElement.scrollWidth") <= 376
            page.screenshot(path=f"{SHOTS}/07-publico-movil.png", full_page=True)

        check("0022604 sitio público en móvil sin desbordes", public_mobile)
        ctx.close()
        browser.close()

        print("\nErrores de consola cliente:", client_errors or "ninguno")
        print("Errores de consola admin:", admin_errors or "ninguno")
        ok = sum(1 for _, s, _ in results if s)
        print(f"\nE2E: {ok}/{len(results)} verificaciones correctas")
        sys.exit(0 if ok == len(results) and not client_errors and not admin_errors else 1)


if __name__ == "__main__":
    main()
