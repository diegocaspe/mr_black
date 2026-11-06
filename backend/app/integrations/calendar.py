"""Integración desacoplada con Google Calendar.

- `NullCalendarProvider`: se usa cuando no hay credenciales OAuth o la barbería no
  conectó su cuenta. Todas las operaciones son no-op → la app funciona sin Google.
- `GoogleCalendarProvider`: usa la API REST v3 con un refresh token (guardado cifrado
  en `integration_credentials`) obtenido mediante el flujo OAuth 2.0 del administrador.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models.setting import IntegrationCredential

logger = logging.getLogger("mrblack.calendar")

PROVIDER = "google_calendar"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "https://www.googleapis.com/auth/calendar.events openid email"


@dataclass
class CalendarEvent:
    summary: str
    description: str
    start: datetime
    end: datetime
    attendee_email: str | None = None


class CalendarProvider(Protocol):
    enabled: bool

    def create_event(self, event: CalendarEvent) -> str | None: ...
    def update_event(self, event_id: str, event: CalendarEvent) -> None: ...
    def delete_event(self, event_id: str) -> None: ...


class NullCalendarProvider:
    enabled = False

    def create_event(self, event: CalendarEvent) -> str | None:
        return None

    def update_event(self, event_id: str, event: CalendarEvent) -> None:
        return None

    def delete_event(self, event_id: str) -> None:
        return None


class GoogleCalendarProvider:
    enabled = True

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self.settings = get_settings()

    def _access_token(self) -> str:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _body(self, event: CalendarEvent) -> dict:
        tz = self.settings.app_timezone
        body = {
            "summary": event.summary,
            "description": event.description,
            "start": {"dateTime": event.start.isoformat(), "timeZone": tz},
            "end": {"dateTime": event.end.isoformat(), "timeZone": tz},
        }
        if event.attendee_email:
            body["attendees"] = [{"email": event.attendee_email}]
        return body

    def _url(self, suffix: str = "") -> str:
        return f"{API_BASE}/calendars/{quote(self.settings.google_calendar_id, safe='')}/events{suffix}"

    def create_event(self, event: CalendarEvent) -> str | None:
        token = self._access_token()
        resp = httpx.post(self._url(), headers={"Authorization": f"Bearer {token}"}, json=self._body(event), timeout=10)
        resp.raise_for_status()
        return resp.json().get("id")

    def update_event(self, event_id: str, event: CalendarEvent) -> None:
        token = self._access_token()
        resp = httpx.patch(
            self._url(f"/{quote(event_id, safe='')}"),
            headers={"Authorization": f"Bearer {token}"},
            json=self._body(event),
            timeout=10,
        )
        resp.raise_for_status()

    def delete_event(self, event_id: str) -> None:
        token = self._access_token()
        resp = httpx.delete(
            self._url(f"/{quote(event_id, safe='')}"), headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
        if resp.status_code not in (200, 204, 404, 410):
            resp.raise_for_status()


def get_calendar_provider(db: Session) -> CalendarProvider:
    settings = get_settings()
    if not settings.google_enabled:
        return NullCalendarProvider()
    cred = db.get(IntegrationCredential, PROVIDER)
    if not cred:
        return NullCalendarProvider()
    data = decrypt_secret(cred.encrypted_data)
    if not data:
        logger.warning("No se pudo descifrar la credencial de Google Calendar (¿cambió SECRET_KEY?).")
        return NullCalendarProvider()
    return GoogleCalendarProvider(json.loads(data)["refresh_token"])


def build_authorization_url(state: str) -> str:
    s = get_settings()
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_and_store(db: Session, code: str) -> str | None:
    """Intercambia el código OAuth por tokens y guarda el refresh token cifrado."""
    s = get_settings()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "code": code,
            "redirect_uri": s.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    tokens = resp.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise ValueError("Google no devolvió un refresh token.")
    email = None
    try:
        info = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=10)
        if info.status_code == 200:
            email = info.json().get("email")
    except httpx.HTTPError:
        pass
    cred = db.get(IntegrationCredential, PROVIDER) or IntegrationCredential(provider=PROVIDER)
    cred.encrypted_data = encrypt_secret(json.dumps({"refresh_token": refresh}))
    cred.account_email = email
    db.add(cred)
    db.commit()
    return email
