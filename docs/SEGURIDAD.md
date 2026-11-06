# Fase 9: Revisión de seguridad

| Área | Medida implementada | Verificación |
|---|---|---|
| Contraseñas | Argon2id (`argon2-cffi`) con rehash automático. Política: ≥ 8 caracteres, letras y números, no comunes. Nunca se devuelven en la API | `test_passwords_are_hashed_with_argon2`, `test_validators` |
| Sesión | JWT HS256 (`JWT_SECRET`) en cookie `HttpOnly` + `SameSite=Lax` (+ `Secure` con `COOKIE_SECURE=true`). El JWT referencia una sesión del servidor revocable. Expira según `ACCESS_TOKEN_EXPIRE_MINUTES` | `test_logout_revokes_session` |
| Revocación | Logout, cambio o restablecimiento de contraseña y desactivación del usuario revocan las sesiones | `test_change_password_*`, `test_deactivate_revokes_sessions` |
| CSRF | Doble envío: cookie `mb_csrf` + cabecera `X-CSRF-Token` obligatoria en POST, PUT, PATCH y DELETE | `test_login_requires_csrf` |
| Autorización | `require_roles(...)` en cada endpoint y verificación de propiedad (un cliente o barbero solo ve lo suyo; las citas o ventas ajenas responden 404) | `test_security_roles.py` |
| Asignación masiva | Esquemas de entrada con `extra="forbid"`: un cliente no puede enviar `role`, `is_active`, `stock`… | `test_cliente_cannot_escalate_to_admin`, `test_unknown_fields_rejected_mass_assignment` |
| Fuerza bruta | 5 fallos por usuario o 20 por IP en 15 min → 429. Recuperación limitada a 3 por usuario cada 15 min | `test_login_rate_limit` |
| Enumeración | Mismo mensaje para usuario inexistente, contraseña incorrecta o cuenta inactiva. La recuperación siempre responde igual | `test_login_wrong_password_generic_message`, `test_forgot_password_unknown_email_same_response` |
| Recuperación | Token aleatorio de 256 bits; en la BD solo su hash; 30 min; un solo uso; tokens anteriores invalidados; se quita de la URL en el navegador | `test_password_reset_full_flow` |
| SQL injection | Solo SQLAlchemy con parámetros enlazados; no se concatena SQL con datos del usuario | revisión de código |
| XSS | Plantilla `html` con escape por defecto en todo el frontend; sin handlers inline; CSP `script-src 'self' https://cdn.jsdelivr.net` (Chart.js con SRI) | `e2e_check.py` (sin errores de consola) |
| Clickjacking / MIME | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` | `test_security_headers` |
| CORS | Cerrado por defecto (mismo origen vía nginx). Se abre solo para los orígenes de `CORS_ORIGINS` | configuración |
| Errores | Mensajes en español sin trazas; `IntegrityError` → "No se pudo guardar la información…"; los detalles van al log | `test_errors_do_not_leak_internals` |
| Secretos | Solo en `.env` (excluido por `.gitignore` y `.dockerignore`). `.env.example` sin valores reales. Refresh token de Google cifrado | búsqueda en el código y en la imagen |
| Pagos | Simulados; nunca se guarda el número completo de tarjeta ni el CVV | `test_checkout_online_card` |
| CSV | Neutraliza fórmulas (`=`, `+`, `-`, `@`) para evitar inyección en Excel | revisión de código |
| Subida de fotos (productos y servicios) | Solo ADMIN y CAJA. El tipo se detecta por la firma de los bytes (JPG, PNG, WebP): un SVG o un HTML con extensión de imagen se rechaza. Máx. 2 MB (también lo limita nginx) y 8 por producto. Se sirven con el `Content-Type` detectado y `nosniff`. Las fotos se guardan en la BD, nunca como archivos ejecutables en el servidor. El navegador elimina los metadatos EXIF (p. ej. GPS) al recodificarlas | `test_product_images.py`, `test_service_details.py` |
| Open redirect | `?next=` solo acepta rutas internas | `js/auth.js::safeNext` |
| Contenedor | Proceso sin root (`appuser`), puertos publicados solo en `127.0.0.1` | `Dockerfile`, `docker-compose.yml` |
| `localStorage` | No se usa para datos ni tokens | búsqueda en el código |

## Recomendaciones para producción

1. Servir detrás de HTTPS y definir `COOKIE_SECURE=true`.
2. Usar secretos únicos y largos (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
3. `SEED_ON_START=false` y cambiar las contraseñas de los usuarios iniciales.
4. `uvicorn --forwarded-allow-ips` debe limitarse a la IP del proxy si el puerto 8000 se expone fuera del host.
5. Configurar un SMTP real con TLS (`SMTP_USE_TLS=true`).
