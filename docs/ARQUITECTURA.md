# Fase 2 — Arquitectura

## 1. Vista general

```text
 Navegador ──HTTP──▶ nginx (frontend :8080) ──/api──▶ FastAPI (backend :8000) ──▶ PostgreSQL 16
                       │ archivos estáticos            │                        
                       │ HTML/CSS/JS                   ├──▶ SMTP (Mailpit en desarrollo)
                                                       └──▶ Google Calendar API (opcional)
```

- **Mismo origen**: nginx sirve el frontend y redirige `/api/*` al backend. El navegador
  solo habla con `http://localhost:8080`, por lo que la cookie de sesión es de primera
  parte y CORS queda cerrado por defecto (`CORS_ORIGINS` solo se usa si se separan dominios).
- El backend también es accesible en `:8000` para la documentación OpenAPI (`/api/docs`).

## 2. Elección del backend: FastAPI

| Criterio | FastAPI | Django | Flask |
|---|---|---|---|
| API REST + validación | Nativa con Pydantic v2 | DRF (capa adicional) | Extensiones |
| Documentación API | OpenAPI/Swagger automática | Requiere paquete | Requiere paquete |
| Tipado / mantenibilidad | Alto | Medio | Bajo |
| Testing | `TestClient` + inyección de dependencias | Bueno | Bueno |
| PostgreSQL | SQLAlchemy 2 + Alembic | ORM propio | SQLAlchemy |

Se eligió **FastAPI + SQLAlchemy 2 + Alembic** porque el frontend es HTML/JS propio
(no se necesitan las plantillas ni el admin de Django), la validación declarativa de
Pydantic encaja con la necesidad de reglas centralizadas que exigen las incidencias,
la inyección de dependencias permite expresar permisos por rol de forma explícita en
cada endpoint, y la documentación de la API se genera sola.

SQLAlchemy se usa en modo **síncrono** (psycopg 3): FastAPI ejecuta los endpoints
síncronos en un pool de hilos, el código es más simple de leer y probar, y la carga
esperada de una barbería no justifica la complejidad asíncrona.

## 3. Capas del backend

```text
backend/app/
├── main.py              # crea la app, middlewares, manejadores de error, routers
├── core/                # configuración, BD, seguridad, dependencias, validadores, errores
├── models/              # tablas SQLAlchemy (una por dominio)
├── schemas/             # contratos Pydantic de entrada/salida
├── services/            # reglas de negocio y transacciones
├── integrations/        # correo SMTP, Google Calendar, PDF
├── api/routes/          # endpoints HTTP delgados: validan, autorizan y delegan
└── seed.py              # datos iniciales de desarrollo
```

- **Routers** no contienen lógica de negocio: obtienen el usuario autenticado, comprueban
  el rol y llaman a un servicio.
- **Services** contienen todas las reglas (transiciones de estado, disponibilidad, stock,
  pagos) y son la única capa que escribe en la BD. Se probaron directamente vía API.
- **Decisión documentada**: no se creó una capa "repositories" separada. SQLAlchemy 2 ya
  es un repositorio/unidad de trabajo; añadir otra capa duplicaría código sin aportar
  aislamiento real. Las consultas reutilizables viven como funciones en cada servicio.

## 4. Base de datos

PostgreSQL 16. Las reglas críticas se refuerzan en la base, no solo en Python:

- `CHECK` de precio (≥ 0.10), rating (0–5), stock (≥ 0), cantidades (> 0), total de venta (> 0).
- **Restricción de exclusión** (`btree_gist`) que impide dos citas activas del mismo
  barbero con rangos de tiempo solapados → la doble reserva es imposible incluso con
  dos peticiones simultáneas.
- `SELECT ... FOR UPDATE` sobre productos al confirmar una venta → el stock no puede
  quedar negativo con compras concurrentes (además del `CHECK stock >= 0`).
- Claves foráneas con `ON DELETE RESTRICT` en datos históricos y eliminación lógica
  (`is_active`) para usuarios, barberos, servicios, productos y categorías.

Las **fotos de productos y servicios** se guardan en la propia base (`product_images`,
`service_images`, `BYTEA`, ambas con `StoredImageMixin`) en lugar de
en un volumen de archivos: entran en los respaldos de PostgreSQL, no se pierden al reconstruir
contenedores y no requieren configurar nginx ni almacenamiento adicional. Los bytes se cargan
de forma diferida (no viajan al listar productos) y `GET /api/product-images/{id}` los sirve
con caché inmutable. La subida usa el cuerpo binario de la petición, sin dependencias extra.
La validación (`app/core/images.py`) y las operaciones de galería (`app/services/image_service.py`)
son comunes a productos y servicios.

Detalle de tablas: `docs/BASE_DE_DATOS.md`. Migraciones: Alembic (`backend/migrations`).

## 5. Autenticación y autorización

| Aspecto | Implementación |
|---|---|
| Hash de contraseñas | Argon2id (`argon2-cffi`), rehash automático si cambian los parámetros |
| Sesión | JWT HS256 firmado con `JWT_SECRET` dentro de una cookie `HttpOnly`, `SameSite=Lax`, `Secure` configurable. El JWT contiene un `sid` que referencia la tabla `user_sessions` → el logout, el cambio de contraseña o la desactivación revocan la sesión al instante |
| Expiración | `ACCESS_TOKEN_EXPIRE_MINUTES` (por defecto 120) |
| CSRF | Doble envío: cookie `mb_csrf` legible por JS + cabecera `X-CSRF-Token` obligatoria en métodos que modifican datos |
| Roles | `ADMIN`, `CAJA`, `BARBERO`, `CLIENTE` (tabla `roles`). Dependencia `require_roles(...)` en cada endpoint |
| Propiedad | Un CLIENTE solo ve/modifica sus citas, carrito, ventas y comprobantes; un BARBERO solo su agenda |
| Rate limiting | Intentos de login guardados en `login_attempts`; tras 5 fallos en 15 min por usuario o 20 por IP se responde 429. Recuperación de contraseña limitada por correo/IP |
| Enumeración | Login y recuperación responden con mensajes genéricos |
| Cabeceras | CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy` (nginx y backend) |

Se descartó guardar el JWT en `localStorage` porque cualquier XSS lo robaría.

## 6. Frontend

- HTML5 + CSS3 propio + JavaScript (módulos ES nativos), sin paso de compilación.
- Se reemplaza Tailwind CDN por una hoja de estilos propia (`css/main.css`) organizada por
  secciones y basada en tokens (variables CSS). Identidad de barbería premium: negro
  `#0D0D0D`, carbón `#171717`, crema `#F1E8D8`, madera `#4A3328`, gris `#858585` y dorado mate
  `#B08D57` solo como acento. Tipografía Cormorant Garamond (títulos) y Manrope (texto), con
  tamaños fluidos (`clamp()`).
- Librerías por CDN con versión fija: Font Awesome 6 (iconos) y Chart.js 4 (gráficos). Las
  animaciones y efectos 3D usan solo CSS y JavaScript propio (sin librerías).
- Páginas:
  - `index.html` — sitio público: hero, servicios, barberos, reserva, tienda.
  - `login.html`, `registro.html`, `recuperar.html`, `restablecer.html` — autenticación.
  - `app.html` — panel privado (SPA con enrutador por hash y menú según rol).
- `js/experience.js` — capa solo de presentación del sitio público: cabecera que cambia al
  hacer scroll, sección activa, menú móvil, revelado con `IntersectionObserver`, parallax del
  hero y profundidad 3D sutil (`perspective`, `translateZ`, `rotateX/Y`) con el puntero. No
  toca datos ni lógica; todo se desactiva con `prefers-reduced-motion`.
- `js/components/product-detail.js` — ficha de producto (galería, precio, stock, cantidad y
  "Añadir al carrito") usada en la tienda pública, en la del cliente y en el panel. Para ADMIN
  y CAJA incluye el gestor de fotos (subir varias o arrastrarlas, ordenar, eliminar y foto por
  enlace); reduce cada foto a 1600 px en el navegador antes de enviarla.
- `js/components/service-detail.js` — ficha de servicio (fotos, precio, duración, oferta, en qué
  consiste, qué incluye y barberos que lo realizan). "Reservar este servicio" emite el evento
  `mb:book-service` y la reserva (`booking.js`) preselecciona el servicio y pasa al paso 2. ADMIN y
  CAJA editan la ficha y las fotos desde ahí o desde Panel → Servicios (CAJA solo ve "Ficha y fotos").
- `js/components/gallery.js` — galería, reducción de fotos y gestor de fotos compartidos por
  ambas fichas.
- `js/api.js` centraliza `fetch`: credenciales, CSRF, errores normalizados y redirección
  al login cuando la sesión expira. `localStorage` solo guarda preferencias de interfaz
  (nunca datos de negocio ni tokens).
- `js/validators.js` replica las reglas del backend únicamente para dar retroalimentación
  inmediata; la validación definitiva siempre es del servidor.

## 7. Integraciones desacopladas

| Integración | Interfaz | Implementaciones |
|---|---|---|
| Correo | `EmailSender.send(to, subject, html, text, attachments)` | `SMTPEmailSender` (SMTP/STARTTLS/SSL), `ConsoleEmailSender` (log). Seleccionado por `EMAIL_BACKEND` |
| Calendario | `CalendarProvider.create/update/delete_event` | `GoogleCalendarProvider` (OAuth 2.0, refresh token cifrado con Fernet) y `NullCalendarProvider` cuando no hay credenciales |
| PDF | `render_receipt_pdf(sale)` | ReportLab |

Los correos y eventos de calendario se ejecutan **después del commit** en tareas en
segundo plano: un fallo de SMTP o Google nunca revierte una cita o venta; se registra
en logs y en `email_log`.

## 8. Docker

| Servicio | Imagen | Puerto |
|---|---|---|
| `db` | postgres:16-alpine | 5433 → 5432 (solo para inspección) |
| `backend` | `Dockerfile` (python:3.12-slim) | 8000 |
| `frontend` | `docker/nginx/Dockerfile` (nginx:alpine) | 8080 |
| `mailpit` | axllent/mailpit (SMTP de pruebas con bandeja web) | 8025 (web), 1025 (SMTP) |

Al iniciar, el backend espera a PostgreSQL, ejecuta `alembic upgrade head` y, si
`SEED_ON_START=true`, carga los datos de desarrollo (idempotente).

## 9. Zona horaria

Las fechas se guardan como `timestamptz` (UTC). La lógica de agenda usa la zona de la
barbería (`APP_TIMEZONE`, por defecto `America/Lima`), de modo que "hora pasada" y
"horario laboral" no dependen del reloj ni de la zona del navegador del cliente.

## 10. Manejo de errores

- Errores de negocio → `AppError(status, code, message)` con mensaje en español para el usuario.
- Errores de validación → 422 con mensajes por campo en español.
- `IntegrityError` y excepciones no controladas → se registran con traza en logs y se
  responde un mensaje genérico ("No se pudo guardar la información. Inténtelo nuevamente.").
- Formato uniforme: `{"error": {"code": "...", "message": "...", "fields": {...}}}`.
