# Fase 3: Base de datos (PostgreSQL 16)

Migraciones: Alembic, en `backend/migrations/versions/`. La migración inicial crea todo el
esquema, la extensión `btree_gist`, la restricción de exclusión de citas, la secuencia de
comprobantes y los catálogos (roles, estados de cita y métodos de pago).

| Migración | Contenido |
|---|---|
| `168b2aa3a159` esquema inicial | Todas las tablas, restricciones, catálogos y secuencias |
| `5c1e7a9d2b40` fotos de producto | Tabla `product_images` (galería de fotos por producto) |
| `8a4f2c6e1d93` ficha de servicio | Columnas `services.details`, `includes` (JSONB) y `offer`; tabla `service_images` |

```bash
docker compose exec backend alembic upgrade head      # aplicar (también se aplica al iniciar)
docker compose exec backend alembic downgrade -1      # revertir la última
docker compose exec backend alembic revision --autogenerate -m "descripcion"   # nueva migración
```

## Entornos

| Entorno | Servidor | Configuración |
|---|---|---|
| Desarrollo | PostgreSQL 16 en Docker (servicio `db`) | `.env` |
| Pruebas | Base `mrblack_test` (Docker o Neon) | `TEST_DATABASE_URL`: se vacía en cada ejecución |
| Producción | Neon (PostgreSQL 16, conexión directa con TLS) | `.env.production` / variables del hosting |

El motor de SQLAlchemy usa `pool_pre_ping` y `pool_recycle=300` porque Neon suspende el compute
inactivo y cierra las conexiones ociosas.

## Prevención de doble reserva

`ex_appointments_no_overlap` (`EXCLUDE USING gist (barber_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
WHERE status IN ('PENDIENTE','CONFIRMADA')`) requiere la extensión `btree_gist`. Rechaza en la propia
base de datos dos citas activas solapadas del mismo barbero, aunque se salte la API o lleguen dos
reservas a la vez. La API lo traduce a `409 slot_taken`. Lo verifican
`test_exclusion_constraint_is_the_one_rejecting_overlaps` (SQL directo) y
`test_concurrent_booking_only_one_wins` (dos solicitudes simultáneas).

## Diagrama (relaciones principales)

```text
roles 1─* users 1─0..1 clients ─┬─* appointments *─1 barbers *─* services (barber_services)
            │                   │        │  └─* appointment_status_history
            │                   │        └─0..1 sales
            │                   └─1 carts 1─* cart_items *─1 products *─1 product_categories
            ├─* user_sessions                                    ├─* inventory_movements
            │                                                    └─* product_images
            ├─* notifications           sales 1─* sale_items (producto XOR servicio)
            ├─* password_reset_tokens   sales 1─* payments *─1 payment_methods
            └─* audit_logs              sales 1─1 receipts
barbers 1─* barber_schedules (semanal) · barbers 1─* barber_time_off (bloqueos) · services 1─* service_images
settings (clave → JSON) · integration_credentials (Google, cifrado) · login_attempts · email_log
```

## Tablas

| Tabla | Propósito | Restricciones clave |
|---|---|---|
| `roles` | ADMIN, CAJA, BARBERO, CLIENTE | `code` único |
| `users` | Cuentas de acceso | `username` y `email` únicos; `password_hash` Argon2id; `is_active` (eliminación lógica); `is_protected` (admin principal) |
| `user_sessions` | Sesiones revocables referenciadas por el JWT | `expires_at`, `revoked_at` |
| `login_attempts` | Rate limiting de login | índices por identificador o IP y fecha |
| `password_reset_tokens` | Recuperación de contraseña | solo se guarda el **hash SHA-256** del token; `expires_at`, `used_at` (un solo uso) |
| `clients` | Ficha del cliente (con o sin cuenta) | `phone` único (normalizado `9XXXXXXXX`); `user_id` único opcional |
| `barbers` | Perfil del barbero | `CHECK rating BETWEEN 0 AND 5` (`NUMERIC(2,1)`); `is_active` y `is_available` |
| `services` | Catálogo de servicios y su ficha | `CHECK price >= 0.10`; `CHECK duration 5–480`; `details` (1000), `includes` JSONB (lista, por defecto `[]`), `offer` (120, aviso informativo) |
| `service_images` | Fotos de referencia del servicio (ADMIN o CAJA) | mismas columnas y reglas que `product_images`; `ON DELETE CASCADE` desde `services` |
| `barber_services` | Servicios que ofrece cada barbero | PK compuesta |
| `barber_schedules` | Horario semanal (0=lunes) | único (barbero, día); `CHECK end > start`; descanso dentro del horario |
| `barber_time_off` | Vacaciones y bloqueos puntuales | `CHECK end_at > start_at` |
| `appointment_statuses` | Catálogo de estados (`is_final`) | FK desde `appointments.status` |
| `appointments` | Citas | `timestamptz` de inicio y fin; `CHECK end > start`; **`EXCLUDE USING gist (barber_id WITH =, tstzrange(start_at,end_at) WITH &&) WHERE status IN ('PENDIENTE','CONFIRMADA')`**; `google_event_id`; `sale_id` (cobro) |
| `appointment_status_history` | Trazabilidad de cada cambio de estado o reprogramación | FK a la cita |
| `product_categories` | Categorías | `name` único |
| `products` | Productos | `CHECK price >= 0.10`, `CHECK stock >= 0`, `CHECK min_stock >= 0`; índice único `lower(name)` |
| `product_images` | Galería de fotos del producto (subidas por ADMIN o CAJA) | bytes en `data` (`BYTEA`, se carga de forma diferida); `content_type` detectado por los bytes; `CHECK size_bytes > 0`; `position` (orden, la primera es la portada); índice (producto, posición); `ON DELETE CASCADE` desde `products`; `uploaded_by` → `users` (`SET NULL`) |
| `inventory_movements` | Entradas, salidas, ajustes, ventas y devoluciones | `stock_before`/`stock_after`, `CHECK stock_after >= 0`, usuario, venta |
| `carts`, `cart_items` | Carrito persistente del cliente | `CHECK quantity > 0` |
| `payment_methods` | ONLINE, YAPE, PLIN, EFECTIVO, LOCAL | `online_allowed`, `counter_allowed`, `immediate` |
| `sales` | Ventas (online / mostrador) | `CHECK total > 0`; estado PAGADA / PENDIENTE_PAGO / ANULADA |
| `sale_items` | Detalle (producto **o** servicio) | `CHECK (product XOR service)`; `CHECK quantity > 0`, `unit_price > 0` |
| `payments` | Pagos simulados | referencia y detalle enmascarado ("Visa •••• 4242"), sin número completo ni CVV |
| `receipts` | Comprobantes B001-00000001 | único (serie, número), secuencia `receipt_number_seq` |
| `notifications` | Notificaciones internas | índice (usuario, leído, fecha) |
| `email_log` | Registro de correos enviados o fallidos | |
| `audit_logs` | Auditoría | usuario, acción, entidad, id, `details` JSONB, IP y agente |
| `settings` | Configuración (negocio, agenda, inventario) | clave → JSONB |
| `integration_credentials` | Refresh token de Google | **cifrado con Fernet** derivado de `SECRET_KEY` |

## Integridad histórica

- Usuarios, barberos, servicios, productos y categorías **no se eliminan físicamente**: se desactivan.
- Las FK desde citas y ventas usan `ON DELETE RESTRICT`.
- Al cambiar el rol de un usuario, el perfil de cliente o barbero se desvincula (`user_id = NULL`)
  pero conserva todas sus citas y ventas.
- Las ventas guardan una copia de la descripción y el precio unitario de cada línea. Los
  comprobantes guardan el nombre del cliente en el momento de la emisión.
