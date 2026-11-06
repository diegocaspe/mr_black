"""Arranque del contenedor: espera a PostgreSQL, aplica migraciones, carga datos de desarrollo
(si SEED_ON_START=true) y reemplaza el proceso por el comando recibido (uvicorn por defecto)."""

import logging
import os
import sys
import time

from sqlalchemy import create_engine, text

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [bootstrap] %(message)s")
log = logging.getLogger("bootstrap")


def wait_for_db(url: str, timeout: int = 60) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    deadline = time.time() + timeout
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            log.info("PostgreSQL disponible.")
            return
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                log.error("PostgreSQL no respondió en %ss: %s", timeout, exc)
                sys.exit(1)
            log.info("Esperando a PostgreSQL…")
            time.sleep(2)
        finally:
            engine.dispose()


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")
    log.info("Migraciones aplicadas.")


def main() -> None:
    settings = get_settings()
    wait_for_db(settings.database_url)
    migrate()
    if settings.seed_on_start:
        from app.seed import run as seed

        seed()
    # Número de procesos: variable WEB_CONCURRENCY (uvicorn la lee; 1 si no está definida).
    # El keep-alive supera al de nginx hacia la API (60 s) para que nginx nunca reutilice una
    # conexión que uvicorn acaba de cerrar (eso produce errores 502 intermitentes bajo carga).
    # Con varios procesos, el supervisor reinicia al que no responde su chequeo de salud: con el CPU
    # saturado 5 s no alcanzan y se pierden las peticiones en curso, por eso se amplía a 30 s.
    cmd = sys.argv[1:] or [
        "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
        "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "75",
        "--timeout-worker-healthcheck", "30",
    ]
    log.info("Iniciando: %s", " ".join(cmd))
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
