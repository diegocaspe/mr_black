/** Shell del panel privado: autenticación, menú por rol, enrutador por hash y notificaciones. */
import { api, currentUser, logout } from '../api.js';
import { $, emptyState, fmtDateTime, html, loading, render, toast, toastError } from '../ui.js';

const ROLE_LABEL = { ADMIN: 'Administrador', CAJA: 'Encargado de caja', BARBERO: 'Barbero', CLIENTE: 'Cliente' };

/**
 * Rutas del panel. `roles` controla el menú y el acceso en la interfaz; los permisos reales se
 * aplican en cada endpoint del backend.
 */
const ROUTES = [
  { path: 'dashboard', title: 'Resumen', icon: 'fa-gauge', roles: ['ADMIN', 'CAJA'], group: 'General', load: () => import('./views/dashboard.js') },
  { path: 'citas', title: 'Citas', icon: 'fa-calendar-days', roles: ['ADMIN', 'CAJA'], group: 'Operación', load: () => import('./views/appointments.js') },
  { path: 'caja', title: 'Venta de mostrador', icon: 'fa-cash-register', roles: ['ADMIN', 'CAJA'], group: 'Operación', load: () => import('./views/counter.js') },
  { path: 'ventas', title: 'Ventas', icon: 'fa-receipt', roles: ['ADMIN', 'CAJA'], group: 'Operación', load: () => import('./views/sales.js') },
  { path: 'clientes', title: 'Clientes', icon: 'fa-users', roles: ['ADMIN', 'CAJA'], group: 'Operación', load: () => import('./views/clients.js') },
  { path: 'inventario', title: 'Inventario', icon: 'fa-boxes-stacked', roles: ['ADMIN', 'CAJA'], group: 'Catálogo', load: () => import('./views/inventory.js') },
  { path: 'productos', title: 'Productos', icon: 'fa-box-open', roles: ['ADMIN'], group: 'Catálogo', load: () => import('./views/products.js') },
  { path: 'servicios', title: 'Servicios', icon: 'fa-scissors', roles: ['ADMIN', 'CAJA'], group: 'Catálogo', load: () => import('./views/services.js') },
  { path: 'barberos', title: 'Barberos', icon: 'fa-user-tie', roles: ['ADMIN'], group: 'Catálogo', load: () => import('./views/barbers.js') },
  { path: 'finanzas', title: 'Finanzas y reportes', icon: 'fa-chart-line', roles: ['ADMIN'], group: 'Administración', load: () => import('./views/finance.js') },
  { path: 'usuarios', title: 'Usuarios', icon: 'fa-user-gear', roles: ['ADMIN'], group: 'Administración', load: () => import('./views/users.js') },
  { path: 'auditoria', title: 'Auditoría', icon: 'fa-shield-halved', roles: ['ADMIN'], group: 'Administración', load: () => import('./views/audit.js') },
  { path: 'configuracion', title: 'Configuración', icon: 'fa-sliders', roles: ['ADMIN'], group: 'Administración', load: () => import('./views/settings.js') },
  { path: 'agenda', title: 'Mi agenda', icon: 'fa-calendar-check', roles: ['BARBERO'], group: 'Mi trabajo', load: () => import('./views/agenda.js') },
  { path: 'mi-horario', title: 'Mi horario', icon: 'fa-clock', roles: ['BARBERO'], group: 'Mi trabajo', load: () => import('./views/my-schedule.js') },
  { path: 'mis-citas', title: 'Mis citas', icon: 'fa-calendar-days', roles: ['CLIENTE'], group: 'Mi cuenta', load: () => import('./views/my-appointments.js') },
  { path: 'reservar', title: 'Reservar cita', icon: 'fa-calendar-plus', roles: ['CLIENTE'], group: 'Mi cuenta', load: () => import('./views/book.js') },
  { path: 'historial', title: 'Mi historial', icon: 'fa-clock-rotate-left', roles: ['CLIENTE'], group: 'Mi cuenta', load: () => import('./views/history.js') },
  { path: 'tienda', title: 'Tienda', icon: 'fa-store', roles: ['CLIENTE'], group: 'Mi cuenta', load: () => import('./views/shop.js') },
  { path: 'compras', title: 'Mis compras', icon: 'fa-bag-shopping', roles: ['CLIENTE'], group: 'Mi cuenta', load: () => import('./views/purchases.js') },
  { path: 'notificaciones', title: 'Notificaciones', icon: 'fa-bell', roles: ['ADMIN', 'CAJA', 'BARBERO', 'CLIENTE'], group: 'Cuenta', load: () => import('./views/notifications.js') },
  { path: 'perfil', title: 'Mi perfil', icon: 'fa-id-card', roles: ['ADMIN', 'CAJA', 'BARBERO', 'CLIENTE'], group: 'Cuenta', load: () => import('./views/profile.js') },
];

const DEFAULT_ROUTE = { ADMIN: 'dashboard', CAJA: 'citas', BARBERO: 'agenda', CLIENTE: 'mis-citas' };

let user = null;
let renderToken = 0;

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [pathPart, query = ''] = raw.split('?');
  const [path, ...params] = pathPart.split('/').filter(Boolean);
  return { path: path || DEFAULT_ROUTE[user.role], params, query: new URLSearchParams(query) };
}

export function navigate(path) {
  if (location.hash === `#/${path}`) route();
  else location.hash = `#/${path}`;
}

function renderSidebar() {
  render($('#sidebar-user'), html`<div class="xs faint" style="letter-spacing:.14em">SESIÓN</div>
    <div class="bold mt-1" style="overflow-wrap:anywhere">${user.full_name}</div>
    <div class="xs gold mt-1">${ROLE_LABEL[user.role]}</div>`);
  const routes = ROUTES.filter((r) => r.roles.includes(user.role));
  const groups = [...new Set(routes.map((r) => r.group))];
  render($('#sidebar-nav'), html`${groups.map((g) => html`<div class="nav-group">${g}</div>
    ${routes.filter((r) => r.group === g).map((r) => html`<a class="nav-link" href="#/${r.path}" data-path="${r.path}">
      <i class="fa-solid ${r.icon}" aria-hidden="true"></i><span>${r.title}</span>
      ${r.path === 'notificaciones' ? html`<span class="nav-badge" data-notif-badge hidden></span>` : ''}</a>`)}`)}`);
}

async function route() {
  const token = ++renderToken;
  const { path, params, query } = parseHash();
  let def = ROUTES.find((r) => r.path === path);
  if (!def || !def.roles.includes(user.role)) {
    if (def) toast('No tienes acceso a esa sección.', 'err');
    def = ROUTES.find((r) => r.path === DEFAULT_ROUTE[user.role]);
    history.replaceState(null, '', `#/${def.path}`);
  }
  document.querySelectorAll('.nav-link[data-path]').forEach((a) => {
    if (a.dataset.path === def.path) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#page-title').textContent = def.title;
  document.title = `${def.title} | Mr Black`;
  closeSidebar();
  const content = $('#content');
  render(content, loading());
  try {
    const mod = await def.load();
    if (token !== renderToken) return;
    const container = document.createElement('div');
    content.replaceChildren(container);
    await mod.default(container, { user, params, query, navigate, refreshNotifications });
  } catch (err) {
    if (token !== renderToken) return;
    console.error(err);
    render(content, emptyState('fa-triangle-exclamation', err?.message || 'No se pudo cargar la sección.'));
  }
}

/* ------------------------------------------------------------------ sidebar responsive */
function openSidebar() {
  $('#sidebar').classList.add('open');
  $('#sidebar-backdrop').classList.add('show');
  $('#sidebar-open').setAttribute('aria-expanded', 'true');
  $('#sidebar-close').focus();
}
function closeSidebar() {
  $('#sidebar').classList.remove('open');
  $('#sidebar-backdrop').classList.remove('show');
  $('#sidebar-open').setAttribute('aria-expanded', 'false');
}
$('#sidebar-open').addEventListener('click', openSidebar);
$('#sidebar-close').addEventListener('click', closeSidebar);
$('#sidebar-backdrop').addEventListener('click', closeSidebar);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('#sidebar').classList.contains('open')) closeSidebar();
});

/* ------------------------------------------------------------------ notificaciones */
async function refreshNotifications() {
  try {
    const { count } = await api.get('/notifications/unread-count');
    const dot = $('#notif-count');
    dot.textContent = count > 99 ? '99+' : count;
    dot.hidden = !count;
    $('#notif-btn').setAttribute('aria-label', `Notificaciones (${count} sin leer)`);
    document.querySelectorAll('[data-notif-badge]').forEach((b) => { b.textContent = count; b.hidden = !count; });
  } catch { /* silencioso */ }
}

async function toggleNotifications() {
  const pop = $('#notif-pop');
  const btn = $('#notif-btn');
  if (!pop.hidden) { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); return; }
  pop.hidden = false;
  btn.setAttribute('aria-expanded', 'true');
  render(pop, loading());
  try {
    const items = await api.get('/notifications', { limit: 8 });
    render(pop, html`<div class="panel-head"><span class="panel-title">Notificaciones</span>
        <button type="button" class="btn btn-ghost btn-xs" data-read-all>Marcar todo como leído</button></div>
      ${items.length ? items.map((n) => html`<button type="button" class="notif-item ${n.is_read ? '' : 'unread'}" data-notif="${n.id}" data-link="${n.link || ''}">
        <span class="dot" aria-hidden="true"></span><span class="grow"><span class="bold small">${n.title}</span><br>
        <span class="small muted">${n.message}</span><br><span class="xs faint">${fmtDateTime(n.created_at)}</span></span></button>`)
        : emptyState('fa-bell-slash', 'No tienes notificaciones.')}
      <div class="center" style="padding:10px"><a href="#/notificaciones" class="small">Ver todas</a></div>`);
  } catch (err) {
    render(pop, emptyState('fa-triangle-exclamation', err.message));
  }
}
$('#notif-btn').addEventListener('click', toggleNotifications);
$('#notif-pop').addEventListener('click', async (e) => {
  const item = e.target.closest('[data-notif]');
  if (e.target.closest('[data-read-all]')) {
    await api.post('/notifications/read-all').catch(toastError);
    $('#notif-pop').hidden = true;
    refreshNotifications();
    return;
  }
  if (e.target.closest('a')) { $('#notif-pop').hidden = true; return; }
  if (!item) return;
  await api.post(`/notifications/${item.dataset.notif}/read`).catch(() => {});
  $('#notif-pop').hidden = true;
  refreshNotifications();
  if (item.dataset.link) location.hash = item.dataset.link.replace(/^#?/, '#');
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('.notif-wrap')) { $('#notif-pop').hidden = true; $('#notif-btn').setAttribute('aria-expanded', 'false'); }
});

/* ------------------------------------------------------------------ sesión */
$('#logout-btn').addEventListener('click', async () => {
  try { await logout(); } catch { /* la cookie se invalida igual */ }
  location.replace('/login.html');
});
window.addEventListener('session-expired', () => {
  toast('Tu sesión expiró. Inicia sesión nuevamente.', 'err');
  setTimeout(() => location.replace(`/login.html?next=${encodeURIComponent(`/app.html${location.hash}`)}`), 900);
});

async function init() {
  try {
    user = await currentUser();
  } catch (err) {
    render($('#content'), emptyState('fa-plug-circle-xmark', err.message));
    return;
  }
  if (!user) {
    location.replace(`/login.html?next=${encodeURIComponent(`/app.html${location.hash}`)}`);
    return;
  }
  renderSidebar();
  window.addEventListener('hashchange', route);
  await route();
  refreshNotifications();
  setInterval(refreshNotifications, 60000);
}

init();
