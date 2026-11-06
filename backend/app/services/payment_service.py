"""Pasarela de pagos SIMULADA. No mueve dinero real ni almacena datos sensibles.

Tarjetas de prueba (pago online):
- cualquier número válido por Luhn se aprueba (p. ej. 4242 4242 4242 4242);
- un número terminado en 0002 simula un rechazo del emisor (p. ej. 4000 0000 0000 0002).
Yape/Plin: el código de aprobación de 6 dígitos "000000" simula un rechazo.
"""

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.core.errors import AppError, BadRequest
from app.core.timeutils import now_local
from app.models.sale import PM_EFECTIVO, PM_LOCAL, PM_ONLINE, PM_PLIN, PM_YAPE
from app.schemas.sale import PaymentDetailsIn


@dataclass
class PaymentResult:
    approved: bool
    pending: bool
    reference: str | None
    payer_detail: str | None
    change_due: Decimal | None = None


def _luhn_ok(number: str) -> bool:
    total, parity = 0, len(number) % 2
    for i, ch in enumerate(number):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _brand(number: str) -> str:
    if number.startswith("4"):
        return "Visa"
    if re.match(r"^(5[1-5]|2[2-7])", number):
        return "Mastercard"
    if re.match(r"^3[47]", number):
        return "Amex"
    return "Tarjeta"


def _reference(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%y%m%d}-{secrets.token_hex(4).upper()}"


def _declined(message: str) -> AppError:
    return AppError(402, "payment_declined", message)


def process(method: str, amount: Decimal, details: PaymentDetailsIn) -> PaymentResult:
    if amount <= 0:
        raise BadRequest("El total a pagar debe ser mayor a S/ 0.00.", code="zero_total")

    if method == PM_ONLINE:
        number = re.sub(r"[\s-]", "", details.card_number or "")
        errors = {}
        if not re.fullmatch(r"\d{13,19}", number) or not _luhn_ok(number):
            errors["payment.card_number"] = "Número de tarjeta inválido."
        if not details.card_holder:
            errors["payment.card_holder"] = "Ingresa el nombre del titular."
        m = re.fullmatch(r"(\d{2})/(\d{2})", (details.card_expiry or "").strip())
        if not m or not 1 <= int(m.group(1)) <= 12:
            errors["payment.card_expiry"] = "Fecha de vencimiento inválida (MM/AA)."
        else:
            month, year = int(m.group(1)), 2000 + int(m.group(2))
            today = now_local()
            if (year, month) < (today.year, today.month):
                errors["payment.card_expiry"] = "La tarjeta está vencida."
        if not re.fullmatch(r"\d{3,4}", details.card_cvv or ""):
            errors["payment.card_cvv"] = "CVV inválido."
        if errors:
            raise BadRequest(next(iter(errors.values())), code="payment_validation", fields=errors)
        if number.endswith("0002"):
            raise _declined("Pago rechazado por el banco emisor (simulación). Prueba con otra tarjeta.")
        return PaymentResult(True, False, _reference("ONL"), f"{_brand(number)} •••• {number[-4:]}")

    if method in (PM_YAPE, PM_PLIN):
        errors = {}
        if not details.wallet_phone:
            errors["payment.wallet_phone"] = "Ingresa el número de celular asociado."
        if not re.fullmatch(r"\d{6}", details.approval_code or ""):
            errors["payment.approval_code"] = "Ingresa el código de aprobación de 6 dígitos."
        if errors:
            raise BadRequest(next(iter(errors.values())), code="payment_validation", fields=errors)
        if details.approval_code == "000000":
            raise _declined(f"{method.title()} rechazó la operación (simulación). Verifica el código e inténtalo nuevamente.")
        phone = details.wallet_phone
        return PaymentResult(True, False, _reference(method[:3]), f"{method.title()} {phone[0]}•••••{phone[-3:]}")

    if method == PM_EFECTIVO:
        received = details.amount_received
        if received is None:
            return PaymentResult(True, False, _reference("EFE"), "Efectivo", None)
        if received < amount:
            raise BadRequest(f"El monto recibido es menor al total (S/ {amount:.2f}).", code="payment_validation",
                             fields={"payment.amount_received": "Monto insuficiente."})
        change = (received - amount).quantize(Decimal("0.01"))
        return PaymentResult(True, False, _reference("EFE"), f"Efectivo · recibido S/ {received:.2f}", change)

    if method == PM_LOCAL:
        return PaymentResult(False, True, None, "Pago en local (pendiente)")

    raise BadRequest("Método de pago no válido.", code="invalid_method")
