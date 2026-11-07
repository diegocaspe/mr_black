import { api } from '../../api.js';
import {
  $, debounce, emptyState, fmtDate, fmtTime, formValues, html, loading, money, raw, render, statusBadge, submitWith,
  todayISO, toast,
} from '../../ui.js';
import { rules, validateForm } from '../../validators.js';
import { appointmentActions, bindAppointmentActions, options, pagination, sortHeader } from '../shared.js';
import { openClientForm } from './clients.js';

export default async function appointmentsView(root) {
  const [services, barbers] = await Promise.all([api.get('/services'), api.get('/barbers/admin')]);
  let clients = await api.get('/clients');
  const state = { status: '', barber_id: '', client: '', date_from: '', date_to: '', hide_attended: true, sort: 'fecha', order: 'desc', page: 1, page_size: 15 };

  render(root, html`
    <div class="page-head"><div><h2>Citas</h2><p>Registra citas, gestiona estados y cobra los servicios atendidos.</p></div></div>
    <div class="grid" style="grid-template-columns:minmax(0,380px) minmax(0,1fr);align-items:start" data-layout>
      <section class="panel panel-pad" aria-labelledby="new-appt">
        <h3 id="new-appt">Registrar cita manual</h3>
        <p class="small muted mt-1">Solo se muestran horarios realmente disponibles del barbero.</p>
        <form id="appt-form" class="grid mt-4" novalidate>
          <div class="field"><label for="ap-client">Cliente <span class="req">*</span></label>
            <div class="flex gap-2"><select id="ap-client" name="client_id" class="select grow" required></select>
            <button type="button" class="btn btn-dark btn-icon" data-new-client aria-label="Registrar nuevo cliente" title="Nuevo cliente"><i class="fa-solid fa-user-plus"></i></button></div></div>
          <div class="field"><label for="ap-service">Servicio <span class="req">*</span></label>
            <select id="ap-service" name="service_id" class="select" required><option value="">Seleccionar…</option>
            ${services.map((s) => html`<option value="${s.id}">${s.name} · ${money(s.price)} · ${s.duration_minutes} min</option>`)}</select></div>
          <div class="field"><label for="ap-barber">Barbero <span class="req">*</span></label>
            <select id="ap-barber" name="barber_id" class="select" required disabled><option value="">Primero elige un servicio</option></select></div>
          <div class="field"><label for="ap-date">Fecha <span class="req">*</span></label>
            <input id="ap-date" name="date" type="date" class="input" min="${todayISO()}" value="${todayISO()}" required></div>
          <div class="field"><label for="ap-slot">Horario <span class="req">*</span></label>
            <select id="ap-slot" name="start_at" class="select" required disabled><option value="">Elige barbero y fecha</option></select>
            <p class="field-hint" id="ap-slot-hint"></p></div>
          <div class="field"><label for="ap-notes">Comentario</label><textarea id="ap-notes" name="notes" class="textarea" rows="2" maxlength="300"></textarea></div>
          <button type="submit" class="btn btn-gold btn-block"><i class="fa-solid fa-calendar-plus" aria-hidden="true"></i> Registrar cita</button>
        </form>
      </section>
      <section class="panel" aria-labelledby="recent">
        <div class="panel-head"><h3 class="panel-title" id="recent">Citas</h3>
          <button type="button" class="btn btn-ghost btn-sm" data-refresh><i class="fa-solid fa-rotate" aria-hidden="true"></i> Actualizar</button></div>
        <form class="filters panel-pad" id="filters" style="border-bottom:1px solid var(--line)">
          <div class="field"><label for="f-status">Estado</label><select id="f-status" name="status" class="select"><option value="">Todos</option>
            ${['PENDIENTE', 'CONFIRMADA', 'ATENDIDA', 'CANCELADA'].map((s) => html`<option value="${s}">${s[0] + s.slice(1).toLowerCase()}</option>`)}</select></div>
          <div class="field"><label for="f-barber">Barbero</label><select id="f-barber" name="barber_id" class="select"><option value="">Todos</option>${options(barbers)}</select></div>
          <div class="field"><label for="f-client">Cliente</label><input id="f-client" name="client" class="input" type="search" placeholder="Nombre o teléfono" maxlength="60"></div>
          <div class="field"><label for="f-from">Desde</label><input id="f-from" name="date_from" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
          <div class="field"><label for="f-to">Hasta</label><input id="f-to" name="date_to" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
          <div class="field"><label class="switch" title="Las atendidas por cobrar siempre se muestran"><input type="checkbox" name="hide_attended" checked> <span>Ocultar atendidas</span></label></div>
          <div class="field"><button type="reset" class="btn btn-dark">Limpiar filtros</button></div>
        </form>
        <div id="appt-table"></div>
      </section>
    </div>`);

  const layout = root.querySelector('[data-layout]');
  const mq = window.matchMedia('(max-width: 1280px)');
  const applyLayout = () => { layout.style.gridTemplateColumns = mq.matches ? '1fr' : 'minmax(0,380px) minmax(0,1fr)'; };
  mq.addEventListener('change', applyLayout);
  applyLayout();

  /* ---------------- formulario de cita manual */
  const form = $('#appt-form', root);
  const fillClients = (selected) => render(form.elements.client_id, html`<option value="">Seleccionar…</option>${options(clients, selected, 'id', (c) => `${c.full_name} · ${c.phone}`)}`);
  fillClients();

  root.querySelector('[data-new-client]').addEventListener('click', () => openClientForm(null, async (c) => {
    clients = await api.get('/clients');
    fillClients(c.id);
  }));

  const loadSlots = async () => {
    const slotSel = form.elements.start_at;
    const hint = $('#ap-slot-hint', root);
    const { service_id: sid, barber_id: bid, date } = formValues(form);
    slotSel.disabled = true;
    hint.textContent = '';
    if (!sid || !bid || !date) { render(slotSel, html`<option value="">Elige barbero y fecha</option>`); return; }
    render(slotSel, html`<option value="">Consultando…</option>`);
    try {
      const av = await api.get('/availability', { barber_id: bid, service_id: sid, date });
      const free = av.slots.filter((s) => s.available);
      render(slotSel, free.length ? html`<option value="">Seleccionar horario…</option>${free.map((s) => html`<option value="${s.start_at}">${s.time}</option>`)}`
        : html`<option value="">Sin horarios disponibles</option>`);
      slotSel.disabled = !free.length;
      hint.textContent = av.message || (free.length ? `${free.length} horario(s) disponible(s).` : '');
    } catch (err) {
      render(slotSel, html`<option value="">No disponible</option>`);
      hint.textContent = err.message;
    }
  };
  form.elements.service_id.addEventListener('change', () => {
    const sid = Number(form.elements.service_id.value);
    const eligible = barbers.filter((b) => b.is_active && b.services.some((s) => s.id === sid));
    const sel = form.elements.barber_id;
    render(sel, html`<option value="">${sid ? 'Seleccionar…' : 'Primero elige un servicio'}</option>
      ${eligible.map((b) => html`<option value="${b.id}" ${b.is_available ? '' : raw('disabled')}>${b.full_name}${b.is_available ? '' : ' (no disponible)'}</option>`)}`);
    sel.disabled = !sid;
    loadSlots();
  });
  form.elements.barber_id.addEventListener('change', loadSlots);
  form.elements.date.addEventListener('change', () => {
    if (form.elements.date.value && form.elements.date.value < todayISO()) {
      toast('La fecha no puede ser anterior a hoy.', 'err');
      form.elements.date.value = todayISO();
    }
    loadSlots();
  });

  const schema = {
    client_id: [rules.required('Selecciona un cliente.')],
    service_id: [rules.required('Selecciona un servicio.')],
    barber_id: [rules.required('Selecciona un barbero.')],
    date: [rules.required('Selecciona una fecha.')],
    start_at: [rules.required('Selecciona un horario disponible.')],
  };
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    const v = formValues(form);
    try {
      await submitWith(form, form.querySelector('[type=submit]'), () => api.post('/appointments', {
        client_id: Number(v.client_id), service_id: Number(v.service_id), barber_id: Number(v.barber_id), start_at: v.start_at, notes: v.notes || null,
      }));
      toast('Cita registrada como pendiente.');
      form.elements.notes.value = '';
      loadSlots();
      loadTable();
    } catch (err) {
      if (err.code?.startsWith('slot')) loadSlots();
    }
  });

  /* ---------------- tabla con filtros, orden y paginación */
  const table = $('#appt-table', root);
  async function loadTable() {
    render(table, loading());
    try {
      const params = { ...state };
      // Elegir "Atendida" en Estado muestra todas las atendidas (el servidor ignora el interruptor).
      if (params.status === 'ATENDIDA') delete params.hide_attended;
      if (params.date_from && params.date_to && params.date_from > params.date_to) {
        render(table, emptyState('fa-calendar-xmark', 'La fecha "Desde" no puede ser posterior a "Hasta".'));
        return;
      }
      const res = await api.get('/appointments', params);
      render(table, res.items.length ? html`<div class="table-wrap"><table class="table responsive">
        <thead><tr>${sortHeader('Fecha', 'fecha', state)}${sortHeader('Cliente', 'cliente', state)}${sortHeader('Barbero', 'barbero', state)}
          ${sortHeader('Servicio', 'servicio', state)}${sortHeader('Estado', 'estado', state)}<th class="text-right">Acciones</th></tr></thead>
        <tbody>${res.items.map((a) => html`<tr>
          <td data-label="Fecha"><span class="bold">${fmtDate(a.start_at)}</span><br><span class="xs faint">${fmtTime(a.start_at)} – ${fmtTime(a.end_at)}</span></td>
          <td data-label="Cliente">${a.client.full_name}<br><span class="xs faint">${a.client.phone}</span></td>
          <td data-label="Barbero">${a.barber.full_name}</td>
          <td data-label="Servicio">${a.service.name}<br><span class="xs faint">${money(a.price)}</span></td>
          <td data-label="Estado">${statusBadge(a.status)}${a.status === 'ATENDIDA' ? html`<br><span class="xs ${a.sale_id ? 'faint' : 'gold'}">${a.sale_id ? 'Cobrada' : 'Por cobrar'}</span>` : ''}</td>
          <td data-label="" class="cell-actions">${appointmentActions(a)}</td></tr>`)}</tbody></table></div>
        ${pagination(res.page, res.page_size, res.total)}` : emptyState('fa-calendar', 'No hay citas con esos filtros.'));
    } catch (err) {
      render(table, emptyState('fa-triangle-exclamation', err.message));
    }
  }
  bindAppointmentActions(table, () => { loadTable(); loadSlots(); });
  table.addEventListener('click', (e) => {
    const s = e.target.closest('[data-sort]');
    const p = e.target.closest('[data-page]');
    if (s) {
      state.order = state.sort === s.dataset.sort && state.order === 'asc' ? 'desc' : 'asc';
      state.sort = s.dataset.sort;
      state.page = 1;
      loadTable();
    } else if (p && !p.disabled) {
      state.page = Number(p.dataset.page);
      loadTable();
    }
  });
  const filters = $('#filters', root);
  const applyFilters = () => {
    Object.assign(state, formValues(filters), { page: 1 });
    loadTable();
  };
  filters.addEventListener('change', applyFilters);
  filters.addEventListener('input', debounce((e) => { if (e.target.name === 'client') applyFilters(); }, 350));
  filters.addEventListener('reset', () => setTimeout(applyFilters, 0));
  filters.addEventListener('submit', (e) => e.preventDefault());
  root.querySelector('[data-refresh]').addEventListener('click', loadTable);
  loadTable();
}
