import { api } from '../../api.js';
import {
  $, debounce, emptyState, fmtDate, fmtDateTime, formValues, html, loading, money, openModal, render, statusBadge,
  submitWith, toast,
} from '../../ui.js';
import { attachPhoneNormalizer, liveValidate, rules, validateForm } from '../../validators.js';

/** Formulario de cliente (crear/editar). Se construye limpio en cada apertura. */
export function openClientForm(client, onSaved) {
  const form = document.createElement('form');
  form.noValidate = true;
  form.autocomplete = 'off';
  render(form, html`<div class="form-grid">
    <div class="field full"><label for="cl-name">Nombre completo <span class="req">*</span></label>
      <input id="cl-name" name="full_name" class="input" maxlength="60" required value="${client?.full_name || ''}"></div>
    <div class="field"><label for="cl-phone">Teléfono <span class="req">*</span></label>
      <input id="cl-phone" name="phone" class="input" inputmode="tel" maxlength="15" placeholder="9XXXXXXXX" required value="${client?.phone || ''}">
      <p class="field-hint">Se guarda como 9 dígitos (ej. 987654321).</p></div>
    <div class="field"><label for="cl-email">Correo</label>
      <input id="cl-email" name="email" type="email" class="input" maxlength="120" value="${client?.email || ''}"></div>
    <div class="field full"><label for="cl-notes">Notas</label>
      <textarea id="cl-notes" name="notes" class="textarea" rows="2" maxlength="500">${client?.notes || ''}</textarea></div>
  </div>
  <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
    <button type="submit" class="btn btn-gold"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> Guardar</button></div>`);
  const m = openModal({ title: client ? 'Editar cliente' : 'Nuevo cliente', kicker: 'Clientes', body: form });
  const schema = { full_name: [rules.personName], phone: [rules.phone], email: [rules.optionalEmail] };
  liveValidate(form, schema);
  attachPhoneNormalizer(form.elements.phone);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    const v = formValues(form);
    const body = { full_name: v.full_name, phone: v.phone, email: v.email.trim() || null, notes: v.notes.trim() || null };
    try {
      const saved = await submitWith(form, form.querySelector('[type=submit]'),
        () => (client ? api.put(`/clients/${client.id}`, body) : api.post('/clients', body)));
      m.close();
      toast(client ? 'Cliente actualizado.' : 'Cliente registrado.');
      onSaved?.(saved);
    } catch { /* errores por campo */ }
  });
}

async function openHistory(id) {
  const box = document.createElement('div');
  render(box, loading());
  openModal({ title: 'Historial del cliente', body: box, size: 'lg' });
  try {
    const h = await api.get(`/clients/${id}/history`);
    render(box, html`<div class="flex justify-between wrap gap-2"><div><h3>${h.client.full_name}</h3>
      <p class="small muted">${h.client.phone}${h.client.email ? ` · ${h.client.email}` : ''}</p></div>
      <span class="badge ${h.client.has_account ? 'b-ok' : 'b-muted'}">${h.client.has_account ? 'Con cuenta' : 'Sin cuenta'}</span></div>
      <h4 class="mt-6 mb-2">Citas (${h.appointments.length})</h4>
      ${h.appointments.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha</th><th>Servicio</th><th>Barbero</th><th>Estado</th></tr></thead>
        <tbody>${h.appointments.map((a) => html`<tr><td data-label="Fecha">${fmtDateTime(a.start_at)}</td><td data-label="Servicio">${a.service.name}</td>
          <td data-label="Barbero">${a.barber.full_name}</td><td data-label="Estado">${statusBadge(a.status)}</td></tr>`)}</tbody></table></div>`
        : emptyState('fa-calendar', 'Sin citas.')}
      <h4 class="mt-6 mb-2">Compras y pagos (${h.sales.length})</h4>
      ${h.sales.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha</th><th>Comprobante</th><th>Detalle</th><th>Estado</th><th class="text-right">Total</th></tr></thead>
        <tbody>${h.sales.map((s) => html`<tr><td data-label="Fecha">${fmtDate(s.created_at)}</td><td data-label="Comprobante">${s.receipt_code}</td>
          <td data-label="Detalle">${s.items.map((i) => `${i.description} ×${i.quantity}`).join(', ')}</td><td data-label="Estado">${statusBadge(s.status)}</td>
          <td data-label="Total" class="text-right">${money(s.total)}</td></tr>`)}</tbody></table></div>` : emptyState('fa-bag-shopping', 'Sin compras.')}`);
  } catch (err) {
    render(box, emptyState('fa-triangle-exclamation', err.message));
  }
}

export default async function clientsView(root) {
  render(root, html`<div class="page-head"><div><h2>Clientes</h2><p>Historial y frecuencia de visitas.</p></div>
      <button type="button" class="btn btn-gold" data-new><i class="fa-solid fa-user-plus" aria-hidden="true"></i> Nuevo cliente</button></div>
    <div class="panel"><div class="panel-pad" style="border-bottom:1px solid var(--line)">
      <div class="field" style="max-width:360px"><label for="cl-q">Buscar</label><input id="cl-q" class="input" type="search" placeholder="Nombre, teléfono o correo" maxlength="60"></div></div>
      <div id="cl-table"></div></div>`);
  const table = $('#cl-table', root);
  let rows = [];
  const load = async () => {
    render(table, loading());
    try {
      rows = await api.get('/clients', { q: $('#cl-q', root).value.trim() });
      render(table, rows.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Cliente</th><th>Teléfono</th><th>Registro</th>
        <th class="text-right">Citas</th><th class="text-right">Atendidas</th><th>Frecuencia</th><th class="text-right">Gastado</th><th class="text-right">Acciones</th></tr></thead>
        <tbody>${rows.map((c) => html`<tr><td data-label="Cliente"><span class="bold">${c.full_name}</span>${c.has_account ? '' : html` <span class="badge badge-plain b-muted">Sin cuenta</span>`}
          ${c.email ? html`<br><span class="xs faint">${c.email}</span>` : ''}</td>
          <td data-label="Teléfono">${c.phone}</td><td data-label="Registro">${fmtDate(c.created_at)}</td>
          <td data-label="Citas" class="text-right">${c.total_appointments}</td><td data-label="Atendidas" class="text-right">${c.attended_appointments}</td>
          <td data-label="Frecuencia">${c.visits_last_30_days} visita(s) / 30 días</td><td data-label="Gastado" class="text-right">${money(c.total_spent)}</td>
          <td data-label="" class="cell-actions"><button type="button" class="btn btn-dark btn-xs" data-history="${c.id}">Historial</button>
            <button type="button" class="btn btn-ghost btn-xs" data-edit="${c.id}"><i class="fa-solid fa-pen" aria-hidden="true"></i> Editar</button></td></tr>`)}</tbody></table></div>`
        : emptyState('fa-users', 'No se encontraron clientes.'));
    } catch (err) { render(table, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.querySelector('[data-new]').addEventListener('click', () => openClientForm(null, load));
  $('#cl-q', root).addEventListener('input', debounce(load, 350));
  table.addEventListener('click', (e) => {
    const h = e.target.closest('[data-history]');
    const ed = e.target.closest('[data-edit]');
    if (h) openHistory(Number(h.dataset.history));
    if (ed) openClientForm(rows.find((c) => c.id === Number(ed.dataset.edit)), load);
  });
  load();
}
