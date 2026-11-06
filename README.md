# Mr Black Barbería: sistema de gestión

Sistema web para la barbería **Mr Black**: reservas con disponibilidad real, horarios de
barberos, tienda con carrito y pagos simulados, inventario, comprobantes PDF, notificaciones,
correo, reportes, auditoría y panel por roles (Administrador, Caja, Barbero y Cliente).

Reemplaza al prototipo `barberia0.3.html`, que guardaba todo en `localStorage`, por una
arquitectura **Frontend → API Python → PostgreSQL** y resuelve las 24 incidencias de
`docs/referencia/incidencias_mr_black.pdf`.

```text
Navegador ──▶ nginx :8080 (HTML/CSS/JS) ──/api──▶ FastAPI :8000 ──▶ PostgreSQL 16
                                                     ├──▶ SMTP (Mailpit en desarrollo)
                                                     └──▶ Google Calendar (opcional)
```

## Tecnologías

| Capa | Tecnología | Motivo |
|---|---|---|
| Backend | Python 3.12, **FastAPI**, SQLAlchemy 2, Alembic, Pydantic v2 | Validación declarativa centralizada, autorización explícita por endpoint, OpenAPI automático y buena base para pruebas (ver `docs/ARQUITECTURA.md`) |
| Base de datos | PostgreSQL 16 (+ `btree_gist`) | Restricción de exclusión contra la doble reserva, `CHECK`, `FOR UPDATE` |
| Seguridad | Argon2id, JWT en cookie HttpOnly con sesión revocable, CSRF de doble envío | |
| Frontend | HTML5, CSS3 propio, JavaScript (módulos ES), Font Awesome, Chart.js | Sin paso de compilación; conserva la identidad negra y dorada |
| PDF / correo | ReportLab, `smtplib` | |
| Infraestructura | Docker Compose: `db`, `backend`, `frontend` (nginx) y `mailpit` | |

## Requisitos

- Docker Desktop (o Docker Engine) con Docker Compose v2.
- Puertos libres en `127.0.0.1`: 8080, 8000, 8025, 1025 y 5433.

## Puesta en marcha

```bash
# 1. Variables de entorno (una sola vez)
cp .env.example .env
#    Edita .env y reemplaza los valores "cambiar…" (contraseña de PostgreSQL y secretos).
#    Genera secretos con:  python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Construir y levantar
docker compose up --build
```

Al iniciar, el backend espera a PostgreSQL, aplica las migraciones y, con `SEED_ON_START=true`,
carga los datos de desarrollo (una sola vez).

| Servicio | URL |
|---|---|
| Aplicación (sitio público y panel) | http://localhost:8080 |
| Panel privado | http://localhost:8080/app.html |
| API | http://localhost:8000/api |
| Documentación de la API (Swagger) | http://localhost:8000/api/docs |
| Bandeja de correos de desarrollo (Mailpit) | http://localhost:8025 |
| PostgreSQL (inspección) | `localhost:5433` |

Comandos útiles:

```bash
docker compose up -d --build          # en segundo plano
docker compose logs -f backend        # logs del backend
docker compose down                   # detener (conserva los datos)
docker compose down -v                # detener y BORRAR la base de datos
docker compose exec backend python -m app.seed   # recargar el seed (si la BD está vacía)
```

## Usuarios de desarrollo

Se crean con el seed. **No se muestran en ninguna pantalla.** Todos usan la contraseña definida en
`SEED_DEFAULT_PASSWORD` (en `.env.example`: `MrBlack.Dev-2026`). Cámbiala para cualquier entorno compartido.

| Rol | Usuario | Notas |
|---|---|---|
| ADMIN | `admin` | Administrador principal (protegido: no se puede desactivar ni degradar) |
| CAJA | `caja` | |
| BARBERO | `barbero1` | Diego C (lun–sáb 09:00–19:30, descanso 13:00–14:00) |
| BARBERO | `barbero2` | Marco Style (valoración 4.5) |
| BARBERO | `barbero3` | Luis Fade (no disponible para reservas) |
| CLIENTE | `987654321` | Carlos Mendoza (también inicia sesión con `carlos.mendoza@example.com`) |
| CLIENTE | `999888777` | Andrea Torres |

El seed también crea un cliente sin cuenta (José Ramírez), 4 servicios, 6 productos (uno dado
de baja y uno con stock bajo), citas y ventas de ejemplo con comprobantes.

**Pagos simulados**: la tarjeta `4242 4242 4242 4242` (cualquier fecha futura y CVV) se aprueba y
una terminada en `0002` se rechaza. En Yape y Plin cualquier código de 6 dígitos se aprueba,
salvo `000000`.

## Variables de entorno

Todas están documentadas en `.env.example`. Las principales:

| Variable | Descripción |
|---|---|
| `DATABASE_URL` / `TEST_DATABASE_URL` | Conexión a PostgreSQL (app / pruebas). La de pruebas es obligatoria, distinta de la app y su nombre debe contener `test`: las pruebas la vacían |
| `ENVIRONMENT` | `development` o `production` (activa las validaciones de producción) |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Credenciales del contenedor `db` |
| `SECRET_KEY`, `JWT_SECRET` | Secretos (≥ 32 caracteres). `SECRET_KEY` también cifra el token de Google |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración de la sesión (120) |
| `COOKIE_SECURE`, `CORS_ORIGINS` | `true` con HTTPS / orígenes permitidos si se separan dominios |
| `FRONTEND_URL`, `APP_TIMEZONE` | URL usada en los correos / zona horaria de la agenda (`America/Lima`) |
| `SEED_ON_START`, `SEED_DEFAULT_PASSWORD` | Carga de datos de desarrollo |
| `EMAIL_BACKEND`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`, `SMTP_FROM` | Correo |
| `NOTIFY_EMAIL` | Bandeja del negocio que recibe un aviso por cada cita nueva |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GOOGLE_CALENDAR_ID` | Google Calendar (opcional) |

## Base de datos y migraciones

El modelo completo (31 tablas, restricciones e índices) está en `docs/BASE_DE_DATOS.md`.

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "cambio"
```

### Producción en la nube: PostgreSQL en Neon

Desarrollo usa el PostgreSQL de Docker (`.env`); producción usa Neon (`.env.production`, que git
ignora; plantilla en `.env.production.example`). El código es el mismo: solo cambia `DATABASE_URL`.

- Usa la cadena **directa** de Neon (sin pooling) con `sslmode=require`. Se puede pegar tal cual
  (`postgresql://…`): la configuración la convierte al driver psycopg 3.
- Neon admite `btree_gist`; la migración inicial la crea (`CREATE EXTENSION IF NOT EXISTS`), por lo
  que no hay pasos manuales.
- Con `ENVIRONMENT=production` la API no arranca si `SEED_ON_START=true`, `COOKIE_SECURE=false` o
  `DEBUG=true`, el seed de desarrollo se niega a ejecutarse y `/api/docs` deja de publicarse.

```bash
# Migrar Neon desde tu equipo (con la imagen del backend ya construida)
docker compose --profile test build tests
docker run --rm --env-file .env.production --entrypoint alembic mrblack-tests current
docker run --rm --env-file .env.production --entrypoint alembic mrblack-tests upgrade head
```

### Despliegue gratuito: Render + Neon

`Dockerfile.render` empaqueta nginx (frontend) y la API en un solo contenedor; `render.yaml` es el
Blueprint del servicio web gratuito. En Render: **New → Blueprint** → elegir el repositorio y
completar `DATABASE_URL` (Neon), `FRONTEND_URL` (la URL `https://….onrender.com`) y las variables
`SMTP_*` (o `EMAIL_BACKEND=console`). `SECRET_KEY` y `JWT_SECRET` se generan solos. Las migraciones
se aplican en cada arranque. El plan gratuito se suspende tras 15 min sin tráfico (la primera
visita tarda ~1 min en despertar).

Administrador inicial en producción (el seed no se ejecuta allí; la contraseña se genera y se
muestra una sola vez, o se toma de `ADMIN_PASSWORD`):

```bash
docker run --rm --env-file .env.production mrblack-render python -m app.create_admin --username admin --email admin@mi-dominio.pe
```

`GET /api/health` devuelve `{"status": "ok", "database": "connected"}` o `503` si la BD no responde.

## Pruebas

```bash
# 224 pruebas de backend (API + reglas de negocio) contra una BD PostgreSQL de pruebas aislada
docker compose --profile test run --rm tests

# 20 verificaciones E2E en navegador real (requiere el stack levantado: docker compose up -d)
docker run --rm --network mrblack_default -v "$PWD/e2e:/e2e" -w /e2e \
  mcr.microsoft.com/playwright/python:v1.48.0-jammy \
  sh -c "pip install -q playwright==1.48.0 && python e2e_check.py"
```

En Windows (PowerShell) reemplaza `$PWD` por `${PWD}`. Las capturas del E2E se guardan en
`e2e/screenshots/`. El E2E crea datos en la base de desarrollo; usa `docker compose down -v`
para empezar de cero.

Cobertura: autenticación, roles, usuarios, barberos, horarios, servicios y su ficha, productos, fotos, inventario, citas
(disponibilidad, doble reserva concurrente, estados y reprogramación), carrito, pagos, ventas,
comprobantes, reportes, notificaciones, Google Calendar (con un proveedor simulado) y seguridad.

## Funcionalidades por rol

- **Cliente**: registro, login, recuperación de contraseña, ficha de cada servicio (fotos, en qué
  consiste, qué incluye, ofertas) con reserva directa, reserva en 4 pasos con horarios
  reales, cancelación y reprogramación, historial, tienda con ficha de producto (galería de
  fotos, stock y cantidad), carrito, pago simulado (online, Yape,
  Plin o en local), comprobantes PDF, notificaciones y perfil.
- **Caja**: dashboard, registro de citas para clientes, confirmación, atención y cobro de
  servicios, venta de mostrador, cobro de pedidos "pago en local", clientes, inventario (lectura),
  fotos de los productos (subir, ordenar y eliminar, desde Inventario o desde la tienda) y ficha y
  fotos de los servicios (desde Panel → Servicios o la web pública; precio y duración los define el administrador).
- **Barbero**: su agenda (confirmar o marcar atendida), su horario y sus bloqueos (vacaciones o permisos).
- **Administrador**: todo lo anterior, además de usuarios, barberos y horarios, servicios con su ficha y
  fotos, productos, fotos de productos y categorías, movimientos de inventario, finanzas con gráficos y exportación CSV,
  auditoría, registro de correos y configuración.

## Correo

En desarrollo los correos van a **Mailpit** (http://localhost:8025): bienvenida, recuperación
de contraseña, cita registrada, confirmada, reprogramada o cancelada, y comprobante de compra
con el PDF adjunto. Si `NOTIFY_EMAIL` está definido, esa bandeja recibe además un aviso por cada
cita nueva con los datos del cliente. Para producción, configura `SMTP_*` (por ejemplo, Gmail con contraseña de
aplicación: `smtp.gmail.com:587`, `SMTP_USE_TLS=true`). Con `EMAIL_BACKEND=console` los correos
solo se escriben en el log. Los envíos son asíncronos: un fallo de SMTP no revierte la operación
y queda registrado en *Auditoría → Correos enviados*.

## Google Calendar (opcional)

La aplicación funciona sin esta integración. Para activarla:

1. En Google Cloud Console habilita **Google Calendar API** y crea credenciales **OAuth 2.0 → Aplicación web**.
2. Agrega como URI de redirección autorizada: `http://localhost:8080/api/integrations/google/callback`.
3. Completa `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `GOOGLE_REDIRECT_URI` en `.env` y reinicia (`docker compose up -d`).
4. En el panel: *Configuración → Google Calendar → Conectar cuenta*.

Desde ese momento, al registrar una cita se crea el evento y se guarda su ID en la cita; al
confirmar o reprogramar se actualiza, y al cancelar se elimina. El refresh token se guarda cifrado.

## Estructura del proyecto

```text
├── backend/
│   ├── app/
│   │   ├── api/routes/      # endpoints (auth, users, clients, catalog, appointments, products, sales, reports, system)
│   │   ├── core/            # config, BD, seguridad, dependencias, validadores, errores, zona horaria
│   │   ├── models/          # tablas SQLAlchemy
│   │   ├── schemas/         # contratos Pydantic
│   │   ├── services/        # reglas de negocio
│   │   ├── integrations/    # email, Google Calendar, PDF
│   │   ├── bootstrap.py     # arranque del contenedor (espera BD, migra, seed)
│   │   ├── seed.py          # datos de desarrollo
│   │   └── main.py
│   ├── migrations/          # Alembic
│   └── tests/               # pytest (224 pruebas)
├── frontend/                # index, login, registro, recuperar, restablecer, app (panel), css, js, assets
├── e2e/                     # pruebas en navegador (Playwright) y capturas
├── docker/                  # nginx y script de inicialización de la BD de pruebas
├── docs/                    # ANALISIS, ARQUITECTURA, BASE_DE_DATOS, API, SEGURIDAD, INCIDENCIAS_RESUELTAS
├── Dockerfile · docker-compose.yml · .env.example · .dockerignore · .gitignore
└── barberia0.3.html         # prototipo original (solo referencia)
```

## Incidencias

Las 24 incidencias del PDF están resueltas y verificadas. La matriz con ID, causa raíz,
solución, archivos y prueba está en **`docs/INCIDENCIAS_RESUELTAS.md`**.

## Documentación

- `docs/ANALISIS.md`: análisis del prototipo y de las incidencias.
- `docs/ARQUITECTURA.md`: decisiones de arquitectura.
- `docs/BASE_DE_DATOS.md`: modelo de datos.
- `docs/API.md`: endpoints y convenciones.
- `docs/SEGURIDAD.md`: revisión de seguridad.
- `docs/INCIDENCIAS_RESUELTAS.md`: matriz de las 24 incidencias.
