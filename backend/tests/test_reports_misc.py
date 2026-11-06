"""Reportes, finanzas (0024831), notificaciones, configuración y Google Calendar desacoplado."""

from app.core.timeutils import today_local


def test_finance_rejects_invalid_years(admin):
    """0024831: años como 0001 o fuera de 2000–2099 se rechazan en el servidor."""
    for f, t in [("0001-01-01", "2026-01-01"), ("2026-01-01", "2100-01-01"), ("1999-12-31", "2026-01-01")]:
        r = admin.get("/api/reports/finance", params={"date_from": f, "date_to": t})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_date", (f, t)


def test_finance_rejects_inverted_range(admin):
    r = admin.get("/api/reports/finance", params={"date_from": "2026-05-10", "date_to": "2026-05-01"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_range"


def test_finance_totals(admin):
    today = today_local()
    r = admin.get("/api/reports/finance", params={"date_from": f"{today.year - 1}-01-01", "date_to": today.isoformat()})
    assert r.status_code == 200
    data = r.json()
    # Seed: productos 18 + 56 + 24 = 98; servicios cobrados 35 + 35 = 70.
    assert float(data["income"]["products"]) == 98.0 and float(data["income"]["services"]) == 70.0
    assert float(data["income"]["total"]) == 168.0 and data["income"]["sales_count"] == 5
    assert {m["code"] for m in data["by_method"]} == {"ONLINE", "YAPE", "PLIN", "EFECTIVO", "LOCAL"}


def test_sales_csv_export(admin):
    today = today_local()
    r = admin.get("/api/reports/sales.csv", params={"date_from": "2026-01-01" if today.year >= 2026 else "2025-01-01", "date_to": today.isoformat()})
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert "comprobante" in r.text.splitlines()[0]


def test_dashboard(caja):
    d = caja.get("/api/reports/dashboard").json()
    for key in ("sales_today", "sales_month", "appointments_today", "pending_appointments", "clients", "low_stock",
                "top_services", "top_barbers", "payment_methods_month", "income_last_14_days", "upcoming"):
        assert key in d
    assert d["clients"] == 3 and d["unpaid_services"] == 1


def test_notifications_read(cliente2):
    items = cliente2.get("/api/notifications").json()
    assert cliente2.get("/api/notifications/unread-count").json()["count"] == len([n for n in items if not n["is_read"]])
    assert cliente2.post("/api/notifications/read-all").status_code == 200
    assert cliente2.get("/api/notifications/unread-count").json()["count"] == 0


def test_settings_update_and_validation(admin, anon):
    bad = admin.put("/api/settings/booking", {"slot_interval_minutes": 0, "min_notice_minutes": 0, "max_days_ahead": 30, "client_cancel_min_hours": 2})
    assert bad.status_code == 422
    ok = admin.put("/api/settings/booking", {"slot_interval_minutes": 15, "min_notice_minutes": 0, "max_days_ahead": 30, "client_cancel_min_hours": 2})
    assert ok.status_code == 200
    assert anon.get("/api/settings/public").json()["booking"]["slot_interval_minutes"] == 15


def test_google_calendar_optional(admin):
    s = admin.get("/api/integrations/google/status").json()
    assert s == {"configured": False, "connected": False, "account_email": None, "calendar_id": "primary"}
    assert admin.get("/api/integrations/google/connect").status_code == 400


def test_calendar_provider_called_when_connected(monkeypatch, cliente):
    """Con credenciales, las citas crean/actualizan/eliminan eventos y se guarda el ID del evento."""
    from app.services import appointment_service

    calls = []

    class FakeProvider:
        enabled = True

        def create_event(self, ev):
            calls.append(("create", ev.summary))
            return "evt-123"

        def update_event(self, event_id, ev):
            calls.append(("update", event_id))

        def delete_event(self, event_id):
            calls.append(("delete", event_id))

    monkeypatch.setattr(appointment_service, "get_calendar_provider", lambda db: FakeProvider())
    from tests.conftest import future_weekday, slot

    d = future_weekday(3)
    a = cliente.post("/api/appointments", {"service_id": 2, "barber_id": 1, "start_at": slot(d, "11:00")}).json()
    cliente.post(f"/api/appointments/{a['id']}/reschedule", {"start_at": slot(d, "15:00")})
    cliente.post(f"/api/appointments/{a['id']}/cancel", {})
    assert [c[0] for c in calls] == ["create", "update", "delete"]
    assert calls[1][1] == "evt-123"


def test_health(anon):
    assert anon.get("/api/health").json() == {"status": "ok", "database": "connected"}
