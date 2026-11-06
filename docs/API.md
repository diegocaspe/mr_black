# API REST

Documentación interactiva generada automáticamente (OpenAPI):

- Swagger UI: http://localhost:8000/api/docs (también http://localhost:8080/api/docs)
- ReDoc: http://localhost:8000/api/redoc

## Convenciones

- JSON en español. Montos como texto decimal (`"35.00"`). Fechas en ISO 8601 con zona horaria.
- Autenticación por cookie `mb_session` (la crean `/api/auth/login` y `/api/auth/register`).
- Las operaciones que modifican datos requieren la cabecera `X-CSRF-Token` con el valor de la cookie `mb_csrf` (`GET /api/auth/csrf`).
- Errores: `{"error": {"code": "...", "message": "...", "fields": {"campo": "mensaje"}}}`
  con 400 (negocio), 401, 402 (pago rechazado), 403, 404, 409 (conflicto o stock), 422 (validación) y 429 (límite).

## Endpoints por recurso

| Recurso | Endpoints | Roles |
|---|---|---|
| Autenticación | `GET csrf` · `POST login, register, logout, forgot-password, reset-password, change-password` · `GET me, session, reset-password/{token}` · `PUT me` | público / autenticado |
| Usuarios | `GET/POST /api/users` · `GET/PUT /api/users/{id}` · `PATCH /{id}/status` · `POST /{id}/password` | ADMIN |
| Clientes | `GET/POST /api/clients` · `GET/PUT /{id}` · `GET /{id}/history` | ADMIN, CAJA |
| Servicios | `GET /api/services`, `/api/services/{id}` (público) · `POST`, `PUT /{id}` | ADMIN |
| Ficha y fotos de servicio | `PATCH /api/services/{id}/content` · `POST /{id}/images` · `DELETE /{id}/images/{image_id}` · `PUT /{id}/images/order` · `GET /api/service-images/{image_id}` (público) | ADMIN, CAJA |
| Barberos | `GET /api/barbers` (público) · `GET /barbers/admin`, `/barbers/{id}` · `POST`, `PUT /{id}` · `GET/PUT /{id}/schedule` · `GET/POST/DELETE /{id}/time-off` | ADMIN (bloqueos: ADMIN o el propio barbero) |
| Disponibilidad | `GET /api/availability?barber_id&service_id&date` | público |
| Citas | `GET/POST /api/appointments` (filtros: `status, barber_id, client_id, client, date_from, date_to, sort, order, page`) · `GET /{id}` · `PATCH /{id}/status` · `POST /{id}/cancel`, `/{id}/reschedule`, `/{id}/charge` | según rol y propiedad |
| Productos | `GET /api/products`, `/api/products/{id}` (tienda) · `GET/POST /api/admin/products` · `PUT /{id}` · `PATCH /{id}/status` · categorías `GET/POST/PUT /api/categories` | ADMIN (lectura: CAJA) |
| Fotos de producto | `GET /api/product-images/{image_id}` (público) · `POST /api/admin/products/{id}/images` · `DELETE /{id}/images/{image_id}` · `PUT /{id}/images/order` · `PATCH /{id}/image` | ADMIN, CAJA |
| Inventario | `GET /api/inventory/summary, alerts, movements` · `POST /movements`, `/min-stock` | ADMIN (lectura: CAJA) |
| Carrito | `GET/DELETE /api/cart` · `POST /cart/items` · `PUT/DELETE /cart/items/{product_id}` · `POST /cart/checkout` | CLIENTE |
| Ventas y pagos | `GET /api/payments/methods` · `GET/POST /api/sales` · `GET /{id}` · `GET /{id}/receipt.pdf` · `POST /{id}/confirm-payment`, `/{id}/cancel` | ADMIN, CAJA; CLIENTE (solo las suyas) |
| Reportes | `GET /api/reports/dashboard` · `GET /finance?date_from&date_to` · `GET /sales.csv` | ADMIN (dashboard: CAJA) |
| Notificaciones | `GET /api/notifications`, `/unread-count` · `POST /{id}/read`, `/read-all` | autenticado |
| Auditoría | `GET /api/audit` · `GET /api/email-log` | ADMIN |
| Configuración | `GET /api/settings/public` · `GET /api/settings` · `PUT /settings/business`, `/settings/booking` | ADMIN |
| Google Calendar | `GET /api/integrations/google/status`, `/connect` · `GET /callback` · `DELETE /api/integrations/google` | ADMIN |
| Salud | `GET /api/health` | público |

## Fotos de producto

Cada producto tiene una **galería de hasta 8 fotos** subidas por el personal (ADMIN y CAJA) y,
opcionalmente, una **foto por enlace** (`image_url`, https o `/assets/…`). Las respuestas de
producto (`ProductPublicOut` y `ProductOut`) incluyen `images: [{"id", "url"}]` en orden.
La **portada** es `image_url` si existe; si no, la primera foto de la galería (también se usa
como miniatura en el carrito).

| Operación | Petición | Notas |
|---|---|---|
| Subir | `POST /api/admin/products/{id}/images` con el **archivo como cuerpo binario** y `Content-Type: image/jpeg`, `image/png` o `image/webp` | Máx. 2 MB y 8 fotos por producto. El tipo se detecta por los bytes del archivo, no por la cabecera. Responde `201` con el producto actualizado |
| Ver | `GET /api/product-images/{image_id}` | Público. `Cache-Control: immutable` (cada foto nueva tiene un id nuevo) |
| Ordenar | `PUT /api/admin/products/{id}/images/order` con `{"image_ids": [3, 1, 2]}` | Debe incluir todas las fotos del producto, sin repetir; la primera es la portada de la galería |
| Eliminar | `DELETE /api/admin/products/{id}/images/{image_id}` | 404 si la foto es de otro producto |
| Foto por enlace | `PATCH /api/admin/products/{id}/image` con `{"image_url": "https://…"}` o `null` | Solo cambia ese campo: CAJA no puede editar precio, nombre ni el resto del producto (`PUT` sigue siendo solo ADMIN) |

Errores específicos: `image_type` (400, formato no permitido), `image_too_large` (400) e
`image_limit` (409, ya hay 8 fotos). El frontend reduce cada foto a 1600 px como máximo y la
recodifica antes de subirla (menos peso y sin metadatos EXIF).

## Ficha del servicio

Las respuestas de servicios (`GET /api/services`, `/api/services/{id}`, `POST` y `PUT`) incluyen la
ficha: `details` (en qué consiste, máx. 1000), `includes` (qué incluye: lista de hasta 10 textos de
2 a 80 caracteres; se limpian espacios, vacíos y duplicados), `offer` (oferta o promoción
informativa, máx. 120) e `images` (galería, igual que en productos). Los servicios anidados en
`/api/barbers` siguen siendo la versión ligera (sin ficha ni fotos).

- `PATCH /api/services/{id}/content` con `{"details": "...", "includes": ["Lavado", "..."], "offer": "..."}`
  (ADMIN y CAJA). Solo cambia la ficha: precio, nombre y duración siguen siendo de ADMIN (`PUT`).
- La **oferta es solo un aviso**: no modifica el precio que se cobra en reservas ni en caja.
- Fotos: mismas reglas y códigos de error que las de producto, en `/api/services/{id}/images…`;
  se sirven en `/api/service-images/{image_id}`.
- `GET /api/services/{id}` responde 404 si el servicio está inactivo, salvo para ADMIN y CAJA.

## Ejemplo con curl

```bash
curl -c cj -b cj http://localhost:8080/api/auth/csrf
TOKEN=$(grep mb_csrf cj | awk '{print $7}')
curl -c cj -b cj -H "X-CSRF-Token: $TOKEN" -H "Content-Type: application/json" \
     -d '{"identifier":"admin","password":"<contraseña>"}' http://localhost:8080/api/auth/login
curl -b cj "http://localhost:8080/api/appointments?status=PENDIENTE&sort=fecha&order=asc"
# Subir una foto al producto 1 (sesión de ADMIN o CAJA)
curl -b cj -H "X-CSRF-Token: $TOKEN" -H "Content-Type: image/jpeg" \
     --data-binary @foto.jpg http://localhost:8080/api/admin/products/1/images
```
