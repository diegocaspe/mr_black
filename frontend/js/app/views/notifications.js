import { api } from '../../api.js';
import { emptyState, fmtDateTime, html, loading, render, toastError } from '../../ui.js';

export default async function notificationsView(root, { refreshNotifications }) {
  render(root, html`<div class="page-head"><div><h2>Notificaciones</h2><p>Citas, compras, pagos y alertas.</p></div>
    <button type="button" class="btn btn-dark" data-all><i class="fa-solid fa-check-double" aria-hidden="true"></i> Marcar todo como leído</button></div><div id="nl" class="panel"></div>`);
  const box = root.querySelector('#nl');
  const load = async () => {
    render(box, loading());
    try {
      const items = await api.get('/notifications', { limit: 100 });
      render(box, items.length ? html`${items.map((n) => html`<button type="button" class="notif-item ${n.is_read ? '' : 'unread'}" data-id="${n.id}" data-link="${n.link || ''}">
        <span class="dot" aria-hidden="true"></span><span class="grow"><span class="bold">${n.title}</span>${n.is_read ? '' : html` <span class="sr-only">(sin leer)</span>`}<br>
        <span class="small muted">${n.message}</span><br><span class="xs faint">${fmtDateTime(n.created_at)}</span></span></button>`)}`
        : emptyState('fa-bell-slash', 'No tienes notificaciones.'));
    } catch (err) { render(box, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.querySelector('[data-all]').addEventListener('click', async () => {
    try { await api.post('/notifications/read-all'); refreshNotifications(); load(); } catch (err) { toastError(err); }
  });
  box.addEventListener('click', async (e) => {
    const it = e.target.closest('[data-id]');
    if (!it) return;
    await api.post(`/notifications/${it.dataset.id}/read`).catch(() => {});
    refreshNotifications();
    if (it.dataset.link) location.hash = it.dataset.link.replace(/^#?/, '#'); else load();
  });
  load();
}
