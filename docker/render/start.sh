#!/bin/sh
# Arranque en Render: migraciones (app.bootstrap) + uvicorn en segundo plano, nginx en $PORT.
# WEB_CONCURRENCY define cuántos procesos de uvicorn atienden la API (1 por defecto). El chequeo de
# salud de 30 s evita que el supervisor reinicie procesos que solo están lentos por carga.
set -e
PORT="${PORT:-10000}"
sed "s/__PORT__/${PORT}/" /etc/nginx/render.conf.template > /etc/nginx/conf.d/default.conf

python -m app.bootstrap uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    --proxy-headers --forwarded-allow-ips 127.0.0.1 --timeout-keep-alive 75 --timeout-worker-healthcheck 30 &
API_PID=$!

# Si la API muere, el contenedor termina y Render lo reinicia.
( wait "$API_PID"; echo "La API terminó; deteniendo nginx."; nginx -s quit ) &
exec nginx -g 'daemon off;'
