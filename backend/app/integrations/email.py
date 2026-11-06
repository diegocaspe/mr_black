"""Servicio de correo desacoplado.

`get_email_sender()` devuelve la implementación según EMAIL_BACKEND:
- smtp    → SMTPEmailSender (STARTTLS/SSL opcional, credenciales desde .env)
- console → ConsoleEmailSender (escribe en el log; útil sin servidor SMTP)
- google_script → GoogleScriptEmailSender (HTTPS a Google Apps Script; para hostings sin SMTP)
"""

import base64
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger("mrblack.email")


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str = "application/pdf"


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    html: str
    text: str
    template: str = "generic"
    attachments: list[Attachment] = field(default_factory=list)


class EmailSender(Protocol):
    def send(self, email: OutgoingEmail) -> None: ...


class SMTPEmailSender:
    def send(self, email: OutgoingEmail) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg["Message-ID"] = make_msgid(domain="mrblack.pe")
        msg.set_content(email.text)
        msg.add_alternative(email.html, subtype="html")
        for att in email.attachments:
            maintype, subtype = att.mime_type.split("/", 1)
            msg.add_attachment(att.content, maintype=maintype, subtype=subtype, filename=att.filename)

        if s.smtp_use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        try:
            if s.smtp_use_tls and not s.smtp_use_ssl:
                server.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass


class ConsoleEmailSender:
    def send(self, email: OutgoingEmail) -> None:
        logger.info("[EMAIL console] Para: %s | Asunto: %s\n%s", email.to, email.subject, email.text)


class GoogleScriptEmailSender:
    """Envía por HTTPS a una aplicación web de Google Apps Script que reenvía desde Gmail.

    Apps Script responde al POST con una redirección 302 hacia el resultado: se sigue la
    redirección y se exige {"ok": true}. Cualquier otra respuesta lanza una excepción, que
    send_email_task registra como ERROR en el log de correos."""

    TIMEOUT = 30.0

    def send(self, email: OutgoingEmail) -> None:
        s = get_settings()
        if not s.google_script_url or not s.google_script_token:
            raise RuntimeError("Faltan GOOGLE_SCRIPT_URL o GOOGLE_SCRIPT_TOKEN para EMAIL_BACKEND=google_script.")
        payload = {
            "token": s.google_script_token,
            "to": email.to,
            "subject": email.subject,
            "html": email.html,
            "text": email.text,
            "fromName": s.app_name,
            "attachments": [
                {"filename": a.filename, "mimeType": a.mime_type, "content": base64.b64encode(a.content).decode("ascii")}
                for a in email.attachments
            ],
        }
        response = httpx.post(s.google_script_url, json=payload, follow_redirects=True, timeout=self.TIMEOUT)
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("ok") is True:
            return
        detail = data.get("error") if isinstance(data, dict) else response.text[:200]
        raise RuntimeError(f"Google Apps Script respondió HTTP {response.status_code}: {detail or 'sin detalle'}")


def get_email_sender() -> EmailSender:
    backend = get_settings().email_backend.strip().lower()
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "google_script":
        return GoogleScriptEmailSender()
    return SMTPEmailSender()


# ---------------------------------------------------------------- plantillas


def render_layout(title: str, intro: str, rows: list[tuple[str, str]] | None = None,
                  button: tuple[str, str] | None = None, footer_note: str | None = None) -> tuple[str, str]:
    """Plantilla HTML con la identidad Mr Black (negro + dorado). Devuelve (html, texto)."""
    s = get_settings()
    rows = rows or []
    rows_html = "".join(
        f'<tr><td style="padding:8px 0;color:#9a9a9a;font-size:13px">{escape(k)}</td>'
        f'<td style="padding:8px 0;color:#f5f5f5;font-size:14px;font-weight:600;text-align:right">{escape(v)}</td></tr>'
        for k, v in rows
    )
    button_html = ""
    if button:
        button_html = (
            f'<p style="margin:28px 0 8px"><a href="{escape(button[1])}" '
            'style="background:#D4AF37;color:#111;text-decoration:none;font-weight:700;'
            f'padding:12px 22px;border-radius:10px;display:inline-block">{escape(button[0])}</a></p>'
        )
    note_html = f'<p style="color:#8a8a8a;font-size:12px;margin-top:24px">{escape(footer_note)}</p>' if footer_note else ""
    html = f"""<!doctype html><html lang="es"><body style="margin:0;background:#121212;font-family:Inter,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#121212;padding:32px 12px"><tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#1e1e1e;border:1px solid #303030;border-radius:16px">
<tr><td style="padding:24px 28px;border-bottom:1px solid #303030">
<span style="display:inline-block;background:#D4AF37;color:#111;font-weight:800;border-radius:10px;padding:8px 10px">MB</span>
<span style="color:#fff;font-weight:800;letter-spacing:2px;margin-left:10px">MR BLACK</span></td></tr>
<tr><td style="padding:28px">
<h1 style="color:#fff;font-size:22px;margin:0 0 12px">{escape(title)}</h1>
<p style="color:#cfcfcf;font-size:15px;line-height:1.6;margin:0 0 16px">{escape(intro)}</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #303030">{rows_html}</table>
{button_html}{note_html}
</td></tr>
<tr><td style="padding:18px 28px;border-top:1px solid #303030;color:#777;font-size:12px">
{escape(s.app_name)} · Este es un mensaje automático, no respondas a este correo.</td></tr>
</table></td></tr></table></body></html>"""
    text_lines = [title, "", intro, ""] + [f"{k}: {v}" for k, v in rows]
    if button:
        text_lines += ["", f"{button[0]}: {button[1]}"]
    if footer_note:
        text_lines += ["", footer_note]
    text_lines += ["", f"— {s.app_name}"]
    return html, "\n".join(text_lines)
