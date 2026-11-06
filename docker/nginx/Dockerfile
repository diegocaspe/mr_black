FROM nginx:1.27-alpine
# La imagen trae 1024 conexiones por proceso de nginx: insuficiente para miles de visitantes.
RUN sed -i -E 's/worker_connections\s+[0-9]+;/worker_connections 4096;/' /etc/nginx/nginx.conf \
    && sed -i '1i worker_rlimit_nofile 16384;' /etc/nginx/nginx.conf
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /usr/share/nginx/html/
EXPOSE 80
