"""Validación común de fotos subidas (productos y servicios).

Las fotos se guardan en la BD (ver `StoredImageMixin`) y se suben como cuerpo binario de la
petición. El tipo se detecta por los primeros bytes: nunca se confía en el Content-Type del cliente.
"""

from fastapi import Request

from app.core.errors import BadRequest

MAX_IMAGES_PER_ITEM = 8
# nginx acepta cuerpos de hasta 2 MB (client_max_body_size); el frontend reduce las fotos antes de subirlas.
MAX_IMAGE_BYTES = 2_000_000
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def _too_large() -> BadRequest:
    return BadRequest("La imagen supera el máximo de 2 MB.", code="image_too_large", fields={"image": "Máximo 2 MB."})


def sniff_image_type(data: bytes) -> str | None:
    """Tipo real según los primeros bytes (JPG, PNG o WebP); None si no es una imagen admitida."""
    for signature, ctype in _SIGNATURES:
        if data.startswith(signature):
            return ctype
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validated_image_type(data: bytes) -> str:
    """Valida tamaño y formato; devuelve el tipo detectado o lanza BadRequest."""
    if not data:
        raise BadRequest("Selecciona una imagen.", fields={"image": "Archivo vacío."})
    if len(data) > MAX_IMAGE_BYTES:
        raise _too_large()
    ctype = sniff_image_type(data)
    if not ctype:
        raise BadRequest("Formato no permitido. Usa JPG, PNG o WebP.", code="image_type", fields={"image": "Formato no permitido."})
    return ctype


async def read_image_body(request: Request) -> bytes:
    """Lee el cuerpo binario rechazando antes de leerlo si el tamaño declarado excede el límite."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
        raise _too_large()
    return await request.body()
