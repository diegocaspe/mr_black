import { api } from '../../api.js';
import { $, debounce, emptyState, fmtDateTime, formValues, html, loading, render } from '../../ui.js';
import { pagination } from '../shared.js';

const ENTITIES = [['', 'Todas'], ['auth', 'Autenticación'], ['user', 'Usuarios'], ['client', 'Clientes'], ['barber', 'Barberos'],
  ['service', 'Servicios'], ['product', 'Productos/Inventario'], ['appointment', 'Citas'], ['sale', 'Ventas'], ['settings', 'Configuración'], ['integration', 'Integraciones']];

function detailText(d) {
  if (!d) return '';
  return Object.entries(d).map(([k, v]) => `${k}: ${Array.isArray(v) && v.length === 2 ? `${v[0] ?? '—'} → ${v[1] ?? '—'}` : typeof v === 'object' && v !== null ? JSON.stringify(v) : v}`).join(' · ');
}

export default async function auditView(root) {
  const state = { action: '', entity: '', date_from: '', date_to: '', page: 1, page_size: 50 };
  let tab = 'audit';
  render(root, html`<div class="page-head"><div><h2>Auditoría</h2><p>Quién hizo qué y cuándo: accesos, cambios, ventas, inventario y correos.</p></div></div>
    <div class="panel"><div class="tabs panel-pad" role="tablist" style="margin:0;padding-bottom:0">
      <button class="tab" role="tab" data-tab="audit" aria-selected="true">Registro de actividad</button>
      <button class="tab" role="tab" data-tab="email" aria-selected="false">Correos enviados</button></div>
      <form class="filters panel-pad" id="af" style="border-bottom:1px solid var(--line)">
        <div class="field"><label for="af-a">Acción</label><input id="af-a" name="action" type="search" class="input" maxlength="60" placeholder="p. ej. LOGIN, CITA, PRODUCTO"></div>
        <div class="field"><label for="af-e">Entidad</label><select id="af-e" name="entity" class="select">${ENTITIES.map(([v, l]) => html`<option value="${v}">${l}</option>`)}</select></div>
        <div class="field"><label for="af-f">Desde</label><input id="af-f" name="date_from" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
        <div class="field"><label for="af-t">Hasta</label><input id="af-t" name="date_to" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
      </form><div id="at"></div></div>`);
  const table = $('#at', root);
  const load = async () => {
    render(table, loading());
    root.querySelectorAll('[data-tab]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.tab === tab)));
    $('#af', root).hidden = tab !== 'audit';
    try {
      if (tab === 'email') {
        const rows = await api.get('/email-log');
        render(table, rows.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha</th><th>Para</th><th>Asunto</th><th>Plantilla</th><th>Estado</th></tr></thead>
          <tbody>${rows.map((r) => html`<tr><td data-label="Fecha">${fmtDateTime(r.created_at)}</td><td data-label="Para">${r.to_address}</td><td data-label="Asunto">${r.subject}</td>
            <td data-label="Plantilla">${r.template}</td><td data-label="Estado"><span class="badge ${r.status === 'ENVIADO' ? 'b-ok' : 'b-danger'}" title="${r.error || ''}">${r.status}</span></td></tr>`)}</tbody></table></div>`
          : emptyState('fa-envelope', 'Aún no se enviaron correos.'));
        return;
      }
      if (state.date_from && state.date_to && state.date_from > state.date_to) {
        render(table, emptyState('fa-calendar-xmark', 'La fecha "Desde" no puede ser posterior a "Hasta".'));
        return;
      }
      const res = await api.get('/audit', state);
      render(table, res.items.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Entidad</th><th>Detalle</th><th>IP</th></tr></thead>
        <tbody>${res.items.map((r) => html`<tr><td data-label="Fecha" class="nowrap">${fmtDateTime(r.created_at)}</td>
          <td data-label="Usuario">${r.user ? r.user.username : '—'}</td><td data-label="Acción"><span class="badge badge-plain b-gold">${r.action}</span></td>
          <td data-label="Entidad">${r.entity}${r.entity_id ? ` #${r.entity_id}` : ''}</td>
          <td data-label="Detalle" class="small" style="max-width:420px;white-space:normal">${detailText(r.details)}</td><td data-label="IP" class="xs faint">${r.ip_address || ''}</td></tr>`)}</tbody></table></div>
        ${pagination(res.page, res.page_size, res.total)}` : emptyState('fa-shield-halved', 'Sin registros.'));
    } catch (err) { render(table, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.addEventListener('click', (e) => {
    const t = e.target.closest('[data-tab]');
    const p = e.target.closest('[data-page]');
    if (t) { tab = t.dataset.tab; load(); }
    if (p && !p.disabled) { state.page = Number(p.dataset.page); load(); }
  });
  const f = $('#af', root);
  const apply = () => { Object.assign(state, formValues(f), { page: 1 }); load(); };
  f.addEventListener('change', apply);
  f.addEventListener('input', debounce((e) => { if (e.target.name === 'action') apply(); }, 400));
  f.addEventListener('submit', (e) => e.preventDefault());
  load();
}
