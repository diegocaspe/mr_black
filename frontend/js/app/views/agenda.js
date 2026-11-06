import { api } from '../../api.js';
import { $, emptyState, fmtDate, fmtTime, formValues, html, loading, render, statusBadge, todayISO } from '../../ui.js';
import { appointmentActions, bindAppointmentActions, pagination } from '../shared.js';

/** Agenda del barbero: solo sus citas (el backend filtra por su perfil). Puede confirmar y marcar atendidas. */
export default async function agendaView(root, { user }) {
  if (!user.barber_id) {
    render(root, emptyState('fa-user-slash', 'Tu cuenta no está vinculada a un perfil de barbero. Contacta al administrador.'));
    return;
  }
  const state = { status: '', date_from: todayISO(), date_to: '', sort: 'fecha', order: 'asc', page: 1, page_size: 25 };
  render(root, html`<div class="page-head"><div><h2>Mi agenda</h2><p>Tus citas asignadas. Confirma las pendientes y marca las atendidas.</p></div></div>
    <div class="panel"><form class="filters panel-pad" id="gf" style="border-bottom:1px solid var(--line)">
      <div class="field"><label for="g-status">Estado</label><select id="g-status" name="status" class="select"><option value="">Todos</option>
        <option value="PENDIENTE">Pendiente</option><option value="CONFIRMADA">Confirmada</option><option value="ATENDIDA">Atendida</option><option value="CANCELADA">Cancelada</option></select></div>
      <div class="field"><label for="g-from">Desde</label><input id="g-from" name="date_from" type="date" class="input" value="${state.date_from}" min="2000-01-01" max="2099-12-31"></div>
      <div class="field"><label for="g-to">Hasta</label><input id="g-to" name="date_to" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
      <div class="field"><button type="button" class="btn btn-dark" data-today>Hoy</button></div>
    </form><div id="gt"></div></div>`);
  const table = $('#gt', root);
  const load = async () => {
    render(table, loading());
    try {
      const res = await api.get('/appointments', state);
      render(table, res.items.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha</th><th>Hora</th><th>Cliente</th><th>Servicio</th><th>Estado</th><th class="text-right">Acciones</th></tr></thead>
        <tbody>${res.items.map((a) => html`<tr><td data-label="Fecha">${fmtDate(a.start_at)}</td><td data-label="Hora" class="bold">${fmtTime(a.start_at)} – ${fmtTime(a.end_at)}</td>
          <td data-label="Cliente">${a.client.full_name}<br><span class="xs faint">${a.client.phone}</span></td><td data-label="Servicio">${a.service.name}${a.notes ? html`<br><span class="xs faint">“${a.notes}”</span>` : ''}</td>
          <td data-label="Estado">${statusBadge(a.status)}</td><td data-label="" class="cell-actions">${appointmentActions(a)}</td></tr>`)}</tbody></table></div>
        ${pagination(res.page, res.page_size, res.total)}` : emptyState('fa-calendar-check', 'No tienes citas en este rango.'));
    } catch (err) { render(table, emptyState('fa-triangle-exclamation', err.message)); }
  };
  bindAppointmentActions(table, load);
  table.addEventListener('click', (e) => { const p = e.target.closest('[data-page]'); if (p && !p.disabled) { state.page = Number(p.dataset.page); load(); } });
  const f = $('#gf', root);
  f.addEventListener('change', () => { Object.assign(state, formValues(f), { page: 1 }); load(); });
  f.addEventListener('submit', (e) => e.preventDefault());
  root.querySelector('[data-today]').addEventListener('click', () => {
    f.elements.date_from.value = todayISO(); f.elements.date_to.value = todayISO();
    Object.assign(state, formValues(f), { page: 1 }); load();
  });
  load();
}
