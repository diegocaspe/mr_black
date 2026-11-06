# Backend Mr Black (FastAPI). El frontend se sirve con nginx (docker/nginx/Dockerfile).
FROM python:3.12-slim

# MALLOC_ARENA_MAX: glibc crea una arena de memoria por hilo y retiene la RAM de cada hash Argon2;
# sin este límite cada proceso de la API crece hasta ~1 GB bajo carga.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app

# INSTALL_DEV=true agrega pytest para ejecutar las pruebas dentro del contenedor.
ARG INSTALL_DEV=false
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser backend/ ./
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["python", "-m", "app.bootstrap"]
