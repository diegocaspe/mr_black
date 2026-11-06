"""EMAIL_BACKEND=google_script: envío por Google Apps Script (httpx simulado).

El simulador reproduce a Apps Script: el POST responde 302 a otra URL y el resultado JSON se
obtiene con GET en la URL de destino."""

import base64
import json

import httpx
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.integrations.email import Attachment, GoogleScriptEmailSender, OutgoingEmail, get_email_sender
from tests.conftest import future_weekday, slot

SCRIPT_URL = "https://script.google.com/macros/s/TEST/exec"


class FakeAppsScript:
    def __init__(self, result=None, status=200, raw=None):
        self.result = {"ok": True} if result is None else result
        self.status, self.raw = status, raw
        self.payloads, self.calls = [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.payloads.append(json.loads(request.content))
            return httpx.Response(302, headers={"Location": "https://script.googleusercontent.com/macros/echo?id=1"})
        if self.raw is not None:
            return httpx.Response(self.status, text=self.raw)
        return httpx.Response(self.status, json=self.result)

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **{k: v for k, v in kwargs.items() if k != "json"}})
        with httpx.Client(transport=httpx.MockTransport(self.handler)) as client:
            return client.post(url, json=kwargs["json"], follow_redirects=kwargs.get("follow_redirects", False),
                               timeout=kwargs.get("timeout"))


@pytest.fixture
def script(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "email_backend", "google_script")
    monkeypatch.setattr(s, "google_script_url", SCRIPT_URL)
    monkeypatch.setattr(s, "google_script_token", "secreto-de-prueba")

    def install(**kw):
        fake = FakeAppsScript(**kw)
        monkeypatch.setattr("app.integrations.email.httpx.post", fake.post)
        return fake

    return install


def _email(**kw):
    return OutgoingEmail(to="cliente@example.com", subject="Asunto", html="<b>Hola</b>", text="Hola", **kw)


def _log():
    with engine.connect() as conn:
        return conn.execute(text("SELECT to_address, template, status, error FROM email_log ORDER BY id")).all()


def test_backend_selected_by_setting(script):
    script()
    assert isinstance(get_email_sender(), GoogleScriptEmailSender)


def test_payload_follows_redirect_with_base64_attachment(script):
    fake = script()
    pdf = b"%PDF-1.4 comprobante"
    GoogleScriptEmailSender().send(_email(attachments=[Attachment("B001-00000001.pdf", pdf)]))

    assert fake.calls == [{"url": SCRIPT_URL, "follow_redirects": True, "timeout": 30.0}]
    p = fake.payloads[0]
    assert p["token"] == "secreto-de-prueba" and p["to"] == "cliente@example.com"
    assert p["subject"] == "Asunto" and p["html"] == "<b>Hola</b>" and p["text"] == "Hola"
    assert p["fromName"] == "Mr Black Barbería"
    assert p["attachments"] == [{"filename": "B001-00000001.pdf", "mimeType": "application/pdf",
                                 "content": base64.b64encode(pdf).decode()}]


@pytest.mark.parametrize("kw, fragment", [
    ({"result": {"ok": False, "error": "Token inválido"}}, "Token inválido"),
    ({"raw": "<html>Error</html>", "status": 500}, "HTTP 500"),
    ({"result": {"status": "sent"}}, "sin detalle"),
])
def test_bad_response_is_logged_as_error(script, kw, fragment):
    from app.services.notification_service import send_email_task

    script(**kw)
    send_email_task(_email(template="prueba"))  # no lanza: registra el fallo
    [(to, template, status, error)] = _log()
    assert (to, template, status) == ("cliente@example.com", "prueba", "ERROR")
    assert fragment in error and "secreto-de-prueba" not in error


def test_missing_configuration_is_logged(script, monkeypatch):
    from app.services.notification_service import send_email_task

    script()
    monkeypatch.setattr(get_settings(), "google_script_token", "")
    send_email_task(_email())
    assert _log()[0][2] == "ERROR" and "GOOGLE_SCRIPT_TOKEN" in _log()[0][3]


def test_new_appointment_emails_client_and_business(script, cliente, monkeypatch):
    fake = script()
    monkeypatch.setattr(get_settings(), "notify_email", "negocio@example.com")
    r = cliente.post("/api/appointments", {"service_id": 1, "barber_id": 2, "start_at": slot(future_weekday(2), "10:00")})
    assert r.status_code == 201, r.text

    sent = {p["to"]: p for p in fake.payloads}
    assert set(sent) == {"carlos.mendoza@example.com", "negocio@example.com"}
    assert sent["carlos.mendoza@example.com"]["subject"] == "Tu cita en Mr Black fue registrada"
    assert sent["negocio@example.com"]["subject"].startswith("Nueva cita: Carlos Mendoza")
    assert "Alexander Huamán" in sent["negocio@example.com"]["text"]
    assert {(row[0], row[2]) for row in _log()} == {("carlos.mendoza@example.com", "ENVIADO"), ("negocio@example.com", "ENVIADO")}
