import logging

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.integrations.email import OutgoingEmail, get_email_sender
from app.models.notification import EmailLog, Notification

logger = logging.getLogger("mrblack.notifications")


def notify(db: Session, user_id: int | None, type_: str, title: str, message: str, link: str | None = None) -> None:
    """Notificación interna; se guarda en la misma transacción que la operación que la origina."""
    if user_id is None:
        return
    db.add(Notification(user_id=user_id, type=type_, title=title[:120], message=message[:500], link=link))


def notify_many(db: Session, user_ids: list[int], type_: str, title: str, message: str, link: str | None = None) -> None:
    for uid in set(user_ids):
        notify(db, uid, type_, title, message, link)


def send_email_task(email: OutgoingEmail) -> None:
    """Se ejecuta en segundo plano después del commit: un fallo de SMTP nunca revierte la operación."""
    status, error = "ENVIADO", None
    try:
        get_email_sender().send(email)
    except Exception as exc:  # noqa: BLE001 - se registra cualquier fallo del proveedor
        status, error = "ERROR", f"{type(exc).__name__}: {exc}"
        logger.error("No se pudo enviar el correo '%s' a %s: %s", email.subject, email.to, error)
    db = SessionLocal()
    try:
        db.add(EmailLog(to_address=email.to, subject=email.subject[:200], template=email.template, status=status, error=error))
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo registrar el envío de correo")
        db.rollback()
    finally:
        db.close()
