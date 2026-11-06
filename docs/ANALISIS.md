# Fase 1 — Análisis del prototipo Mr Black

Documento de análisis previo a la reconstrucción. Fuentes:

- `barberia0.3.html` (prototipo, 801 líneas, una sola página con HTML + Tailwind CDN + JS inline).
- `docs/referencia/incidencias_mr_black.pdf` (24 incidencias, especificación de aceptación).

---

## 1. Resumen del prototipo

Aplicación de una sola página que simula todo el sistema en el navegador. Toda la
"base de datos" es un objeto JSON guardado en `localStorage` (`mrblack_db_v1`) y la
sesión es otro valor de `localStorage` (`mrblack_session_v1`) que solo contiene el
`userId`. No existe servidor: cualquier persona puede abrir la consola y modificar
usuarios, roles, precios, stock o citas.

### 1.1 Identidad visual (se conserva)

| Elemento | Valor en el prototipo |
|---|---|
| Fondo | `#121212`, paneles `#1e1e1e` / `#242424`, sidebar `#151515` |
| Acento | Dorado `#D4AF37` (`--gold`) |
| Tipografía | Inter 400–800 (Google Fonts) |
| Iconografía | Font Awesome 6 |
| Marca | Monograma "MB" en cuadrado dorado, "MR BLACK / BARBER SHOP" con tracking amplio |
| Hero | Gradiente oscuro con brillo radial dorado y cuadrícula sutil de 42px |
| Componentes | Paneles redondeados (16px) con borde `#303030`, hover dorado, botones dorado/oscuro/peligro, badges de estado por color, toasts arriba a la derecha |
| Tono | "Experiencia premium", "Tu estilo, nuestra pasión." |

### 1.2 Navegación

- **Pública**: header fijo (Servicios, Barberos, Tienda, Agendar), hero, tarjetas de
  servicios, equipo de barberos, asistente de reserva en 4 pasos, tienda y footer.
- **Privada**: sidebar con menú por rol + barra superior con título y "Vista pública".

### 1.3 Funcionalidad por rol

| Rol | Funciones en el prototipo |
|---|---|
| Visitante | Ver servicios, barberos, productos; registrarse; iniciar sesión |
| Cliente | Reservar (servicio → barbero → fecha/hora → confirmar), ver "Mis citas", cancelar, reprogramar, historial (atendidas + compras), carrito, compra con pago "online"/"local" |
| Caja | Registrar cita manual, tabla de citas con cambio de estado libre, venta de mostrador de un producto |
| Barbero | Ver su agenda (solo lectura) |
| Admin | Resumen (ingresos, citas, clientes, productos, próximas citas, alertas de stock), citas (filtro fecha/estado), productos (CRUD, baja lógica, umbral global de stock), barberos (alta/edición), clientes (historial, frecuencia de visitas 30 días), usuarios (alta, activar/desactivar), finanzas por rango |

---

## 2. Entidades detectadas y relaciones

Modelo implícito en `seedDB()`:

```text
users ── (clientId) ──> clients
users ── (barberId) ──> barbers
barbers.services[] ──> SERVICES (constante JS, no editable)
appointments: clientId, barberId, serviceId, date "YYYY-MM-DD", time "HH:MM", status, price
products: name, price, stock, active, description, icon
sales: clientId, items[{productId, name, qty, price}], total, payment ("online"|"local"), date
carts: { clientId: { productId: qty } }
settings: { lowStock: 3, currency: "PEN" }
```

Carencias del modelo:

- Servicios codificados en una constante (`SERVICES`); no se pueden administrar.
- Horario fijo `TIMES` (09:00–19:00 cada 30 min) igual para todos los barberos.
  No hay días laborables, descansos, vacaciones ni bloqueos; solo un booleano `available`.
- La cita guarda `date` + `time` como texto, sin hora de fin ni zona horaria.
- No hay categorías, imagen ni stock mínimo por producto; no hay movimientos de inventario.
- No hay pagos, comprobantes, notificaciones, auditoría ni recuperación de contraseña.
- Las ventas guardan el nombre del producto, pero no hay número de comprobante.
- Las contraseñas se guardan en texto plano (`password:'1234'`).

### Entidades para el sistema nuevo

usuarios, roles, sesiones, intentos de login, clientes, barberos, servicios,
barbero↔servicio, horarios semanales (con descanso), bloqueos/vacaciones, citas,
estados de cita, historial de estados, categorías, productos, movimientos de
inventario, carritos, ítems de carrito, métodos de pago, ventas, ítems de venta
(producto o servicio), pagos, comprobantes, notificaciones, registro de correos,
auditoría, tokens de recuperación, configuración e integraciones (Google Calendar).
El detalle está en `docs/BASE_DE_DATOS.md`.

---

## 3. Reglas de negocio identificadas

1. Un cliente se identifica por su teléfono peruano (9 dígitos, empieza con 9), que
   en el prototipo es además su usuario de acceso.
2. Una cita nace `pendiente`. Estados: pendiente, confirmada, atendida, cancelada.
3. No se puede marcar `atendida` una cita futura (única regla de estado del prototipo).
4. Un horario está ocupado si hay otra cita no cancelada del mismo barbero a la misma
   hora exacta.
5. Un barbero solo ofrece ciertos servicios; solo los barberos "disponibles" se pueden elegir.
6. La venta descuenta stock; no se puede vender más que el stock.
7. Producto "dado de baja" (`active=false`) no aparece en la tienda.
8. La cuenta `admin` principal no se puede desactivar.
9. Ingresos = ventas + citas atendidas en el rango.
10. Frecuencia de visitas = citas atendidas de los últimos 30 días.

---

## 4. Problemas encontrados (más allá del PDF)

| # | Problema | Impacto |
|---|---|---|
| P1 | Toda la persistencia en `localStorage` | Datos por navegador, editables por el usuario, sin concurrencia |
| P2 | Contraseñas en texto plano y sesión = `userId` en `localStorage` | Cualquiera se convierte en admin editando un valor |
| P3 | Autorización solo en el cliente (`allowed[u.role]`) | No hay frontera de seguridad |
| P4 | **Solapamiento de citas**: solo se compara la hora exacta | Un "Corte + Barba" (70 min) a las 09:00 no bloquea 09:30 ni 10:00 |
| P5 | Reprogramar **cancela la cita original antes** de elegir la nueva | Si el cliente abandona, pierde la cita |
| P6 | Fechas con la zona del navegador | Un cliente con otra zona horaria ve horas "pasadas" o "futuras" incorrectas |
| P7 | `productById`/`barberById` llaman a `getDB()` y devuelven **otra copia** del objeto | Las ediciones se hacen sobre una copia que no se guarda (ver 0024798, 0024802) |
| P8 | Modal se cierra con `click` cuyo `target` es el overlay | Arrastrar una selección fuera del modal lo cierra (0022677) |
| P9 | Validaciones solo con atributos HTML / JS | Se omiten con la consola o una petición directa |
| P10 | Venta de mostrador de un solo producto, sin comprobante | No sirve para operación real |
| P11 | Carrito sin revalidar precio/estado al pagar | Se puede comprar un producto que se dio de baja después de agregarlo |
| P12 | Ingresos sumando citas atendidas sin registro de cobro | No existe trazabilidad de pago del servicio |
| P13 | Estadísticas del hero codificadas (4.9, 3 barberos, +500) | Información falsa al cambiar datos |
| P14 | Tailwind por CDN en runtime | No recomendado para producción, aviso en consola |
| P15 | Fotos de `i.pravatar.cc` sin validación ni respaldo | Imágenes rotas o URLs arbitrarias |
| P16 | Sin auditoría | No se sabe quién cambió un estado, un precio o un rol |

---

## 5. Análisis de las 24 incidencias (causa raíz en el prototipo)

| ID | Incidencia | Causa raíz en `barberia0.3.html` |
|---|---|---|
| 0024799 | Credenciales visibles en login | Texto fijo `Demo: admin/1234 ...` en `openLogin()` (línea 477) y placeholder con nombres de usuario |
| 0024819 | Login vacío sin mensaje | Solo `required` nativo; `login()` no valida ni marca campos; no hay mensajes por campo |
| 0024792 | Contraseña débil / registro sin validar | `minlength="4"`; sin política ni medidor; validaciones solo en JS del navegador |
| 0024830 | Sin estado inicial al crear cuenta | `saveUser()` fija `active:true`; el formulario no tiene control de estado |
| 0024827 / 0022630 | No se puede editar usuario ni rol | No existe función de edición; la tabla solo tiene "Activar/Desactivar" |
| 0024805 | El formulario conserva datos anteriores | El formulario no se reinicia explícitamente (autocompletado del navegador y estado reutilizado) |
| 0024803 | Teléfono en varios formatos | Normalización solo en el evento `input` del navegador; la capa de datos acepta cualquier texto; no existe validación centralizada |
| 0022677 | Modal se cierra al seleccionar texto | `closeModal(e)` usa el `click`: si el `mousedown` ocurre en un input y el `mouseup` en el overlay, el `click` llega al overlay |
| 0024829 | Datos extremos en barbero | Rating `min=1 max=5` solo HTML, sin control de decimales; URL de foto sin validar; sin `maxlength` en foto |
| 0024822 | Rating mal redondeado | `stars()` usa `Math.round(rating)`; no hay media estrella |
| 0024802 / 0024794 | Editar barbero no guarda | `saveBarber()` edita `barberById(id)`, que obtiene **otra** copia de `getDB()`; luego guarda `db` sin cambios y muestra éxito igualmente |
| 0024828 | Nombre de producto con símbolos | `saveProduct()` no valida el nombre |
| 0022634 | Compra con precio 0 | `Number('0.000000000001')` aceptado; `min="0"`; sin redondeo a 2 decimales; checkout no verifica total > 0 |
| 0024798 | "Dar de baja" no funciona | `toggleProduct()` modifica `productById(id)` (otra copia) y guarda `db` sin cambios; el toast se muestra igual |
| 0024818 | Mínimo de stock no aplica alertas | Umbral global único sin stock mínimo por producto, resaltado casi invisible y alertas solo calculadas al abrir el resumen |
| 0024820 | Sin aviso de falta de stock | Botón deshabilitado sin explicación; mensajes no indican unidades restantes; la cantidad no se limita al stock |
| 0024817 | Métodos de pago | El pago es un texto libre con dos valores (`online`/`local`); Efectivo/Yape/Plin agrupados; no existe entidad de pago |
| 0022585 | Reserva en horas pasadas | `isPastSlot()` depende del reloj y zona del navegador; no hay validación de servidor |
| 0022625 | Estados de cita inconsistentes | `changeAppointmentStatus()` acepta cualquier transición (solo bloquea "atendida" en el futuro) |
| 0022600 | Sin filtros/orden en citas | La tabla de Caja no tiene filtros; la de Admin solo fecha exacta y estado |
| 0024831 | Años inválidos en Finanzas | Inputs `date` sin `min`/`max`; comparación de cadenas sin validar |
| 0022604 | No responsive | Breakpoints mezclados (Tailwind `md` = 768px vs CSS 640px), sidebar oculto sin overlay, tablas `nowrap`, formularios en grid fijo |

---

## 6. Dependencias y decisiones derivadas del análisis

- Las incidencias de validación (0024829, 0024828, 0024803, 0024792, 0022634, 0024831)
  comparten causa: no hay una capa de validación central. Se crea un **módulo único
  de reglas** en el backend (`app/core/validators.py`), espejado en el frontend
  (`frontend/js/validators.js`) solo para UX.
- 0024798 y 0024802/0024794 comparten causa: mutación de una copia y mensaje de éxito
  incondicional. En el sistema nuevo cada guardado es una transacción en PostgreSQL y el
  frontend muestra éxito **solo** con respuesta 2xx y vuelve a leer el recurso.
- 0022585, 0022625 y la doble reserva requieren lógica en el servidor y restricciones
  en la base de datos (restricción de exclusión por rango de tiempo).
- 0024818 y 0024820 requieren stock mínimo por producto, alertas calculadas en consulta
  (no en caché) y validación de stock con bloqueo de fila en la compra.
- 0024817 requiere un catálogo de métodos de pago y una entidad de pago separada de la venta.

---

## 7. Funcionalidad que se conserva y se amplía

| Prototipo | Sistema nuevo |
|---|---|
| Asistente de 4 pasos | Igual, con disponibilidad calculada por el backend según horario, descansos, bloqueos, duración y citas existentes |
| Mis citas: cancelar / reprogramar | Reprogramación atómica (la cita original solo cambia cuando el nuevo horario se confirma) |
| Venta de mostrador de 1 producto | Venta de mostrador con varios productos y comprobante |
| Umbral global de stock | Stock mínimo por producto + acción para aplicar un mínimo a todos |
| Pago online/local | 5 métodos: online simulado, Yape, Plin, efectivo, pago en local |
| Frecuencia de visitas | Se mantiene en el historial del cliente |
| Finanzas por rango | Finanzas con validación de rango, gráficos y desglose por método |
| — | Comprobantes PDF, notificaciones, correo, auditoría, inventario, horarios, Google Calendar |
