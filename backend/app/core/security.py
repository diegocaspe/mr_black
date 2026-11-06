import base64
import hashlib
import hmac
import secrets
import threading
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

SESSION_COOKIE = "mb_session"
CSRF_COOKIE = "mb_csrf"
CSRF_HEADER = "X-CSRF-Token"

# Argon2id con el perfil mínimo de OWASP (19 MiB, 2 iteraciones, 1 hilo). El perfil por defecto de
# argon2-cffi usa 64 MiB por hash: con muchos inicios de sesión simultáneos agota la RAM del servidor.
# Los hashes antiguos se siguen verificando y se actualizan al iniciar sesión (needs_rehash).
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
# Limita los hashes simultáneos por proceso; el resto espera turno en lugar de competir por RAM y CPU.
_hash_slots = threading.BoundedSemaphore(get_settings().password_hash_concurrency)
# Hash ficticio para igualar el tiempo de respuesta cuando el usuario no existe.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-1")


def hash_password(password: str) -> str:
    with _hash_slots:
        return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        with _hash_slots:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: int, session_id: str, role: str) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "sid": session_id, "role": role, "iat": now, "exp": expires, "iss": "mrblack"}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_access_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="mrblack",
            options={"require": ["exp", "sub", "sid"]},
        )
    except jwt.PyJWTError:
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


def new_reset_token() -> tuple[str, str]:
    """Devuelve (token en claro para el enlace, hash SHA-256 para guardar)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    key = hashlib.sha256(("fernet:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def sign_state(value: str) -> str:
    """Firma HMAC para el parámetro `state` de OAuth."""
    sig = hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def verify_state(state: str) -> str | None:
    value, _, sig = state.rpartition(".")
    expected = hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
    return value if value and hmac.compare_digest(sig, expected) else None
