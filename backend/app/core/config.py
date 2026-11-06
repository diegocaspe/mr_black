import os
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_db_url(url: str) -> str:
    """Usa siempre el driver psycopg 3. Neon y otros proveedores entregan `postgresql://` o
    `postgres://`, que SQLAlchemy asociaría a psycopg2 (no instalado)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    # ENV_FILE permite elegir otro archivo (p. ej. `.env.production` para operar contra Neon).
    model_config = SettingsConfigDict(env_file=os.environ.get("ENV_FILE", ".env"), extra="ignore")

    app_name: str = "Mr Black Barbería"
    environment: str = "development"  # development | production | test
    debug: bool = False

    database_url: str = "postgresql+psycopg://mrblack:mrblack@localhost:5432/mrblack"
    # Pool por proceso de uvicorn: conexiones totales = WEB_CONCURRENCY × (pool_size + max_overflow),
    # que debe quedar por debajo del máximo de conexiones del PostgreSQL (Neon).
    db_pool_size: int = Field(10, ge=1)
    db_max_overflow: int = Field(10, ge=0)
    # Segundos esperando una conexión libre antes de responder 503 (en vez de colgar la petición).
    db_pool_timeout: int = Field(10, ge=1)

    # Hashes Argon2 simultáneos por proceso (cada uno usa ~19 MB de RAM y un núcleo de CPU).
    password_hash_concurrency: int = Field(2, ge=1)

    secret_key: str = Field(min_length=32)
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    password_reset_expire_minutes: int = 30

    cookie_secure: bool = False
    cookie_domain: str | None = None
    cors_origins: str = ""

    frontend_url: str = "http://localhost:8080"
    app_timezone: str = "America/Lima"

    # Rate limiting de login
    login_max_failures_per_user: int = 5
    login_max_failures_per_ip: int = 20
    login_window_minutes: int = 15

    # Correo
    email_backend: str = "smtp"  # smtp | console
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    smtp_use_ssl: bool = False
    smtp_from: str = "Mr Black Barbería <no-reply@mrblack.pe>"
    notify_email: str = ""  # bandeja del negocio que recibe un aviso por cada cita nueva (vacío: sin aviso)

    # Google Calendar (opcional)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_calendar_id: str = "primary"

    seed_on_start: bool = False
    seed_default_password: str = ""

    @field_validator("cookie_domain", mode="before")
    @classmethod
    def empty_domain(cls, v):
        return v or None

    @field_validator("database_url")
    @classmethod
    def driver_psycopg(cls, v: str) -> str:
        return normalize_db_url(v)

    @model_validator(mode="after")
    def production_guard(self):
        """Impide arrancar en producción con una configuración insegura."""
        if self.is_production:
            problems = []
            if self.seed_on_start:
                problems.append("SEED_ON_START debe ser false (el seed crea usuarios demo con contraseña conocida)")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE debe ser true (HTTPS)")
            if self.debug:
                problems.append("DEBUG debe ser false")
            if problems:
                raise ValueError("Configuración de producción inválida: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)


@lru_cache
def get_settings() -> Settings:
    return Settings()
