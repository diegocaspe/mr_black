import { api } from '../../api.js';
import { mountPaymentSelector, paymentPayload, paymentSchema } from '../../components/cart.js';
import {
  $, debounce, emptyState, fmtDateTime, formValues, html, loading, money, openModal, render, statusBadge, submitWith, toast,
} from '../../ui.js';
import { validateForm } from '../../validators.js';
import { openSaleDetail, pagination } from '../shared.js';

async function openConfirmPayment(sale, refresh) {
  const methods = (await api.get('/payments/methods')).filter((m) => m.counter_allowed);
  const form = document.createElement('form');
  form.noValidate = true;
  render(form, html`<div class="panel panel-pad" style="background:#191919">
      <div class="summary-row"><span>Pedido</span><b>${sale.receipt_code}</b></div>
      <div class="summary-row"><span>Cliente</span><b>${sale.client ? sale.client.full_name : 'Cliente varios'}</b></div>
      <div class="summary-row"><span class="bold" style="color:#fff">Total a cobrar</span><b class="gold">${money(sale.total)}</b></div></div>
    <div class="mt-5" data-pay-methods></div><div class="pay-panel" data-pay-fields></div>
    <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
      <button type="submit" class="btn btn-gold"><i class="fa-solid fa-check" aria-hidden="true"></i> Registrar cobro</button></div>`);
  const m = openModal({ title: 'Cobrar pedido en local', body: form, size: 'lg' });
  mountPaymentSelector(form, methods);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const method = form.elements.payment_method.value;
    if (!validateForm(form, paymentSchema(method))) return;
    try {
      const res = await submitWith(form, form.querySelector('[type=submit]'),
        () => api.post(`/sales/${sale.id}/confirm-payment`, { payment_method: method, payment: paymentPayload(formValues(form)) }));
      m.close();
      toast('Pago registrado.');
      openSaleDetail(res.id, refresh, res.change_due);
      refresh();
    } catch { /* mostrado */ }
  });
}

export default async function salesView(root, { params }) {
  const state = { status: '', channel: '', method: '', client: '', date_from: '', date_to: '', page: 1, page_size: 20 };
  render(root, html`<div class="page-head"><div><h2>Ventas</h2><p>Consulta ventas, comprobantes y cobra pedidos pendientes.</p></div>
      <a href="#/caja" class="btn btn-gold"><i class="fa-solid fa-cash-register" aria-hidden="true"></i> Nueva venta</a></div>
    <div class="panel"><form class="filters panel-pad" id="sf" style="border-bottom:1px solid var(--line)">
      <div class="field"><label for="sf-status">Estado</label><select id="sf-status" name="status" class="select"><option value="">Todos</option>
        <option value="PAGADA">Pagada</option><option value="PENDIENTE_PAGO">Pago pendiente</option><option value="ANULADA">Anulada</option></select></div>
      <div class="field"><label for="sf-channel">Canal</label><select id="sf-channel" name="channel" class="select"><option value="">Todos</option>
        <option value="ONLINE">Tienda online</option><option value="MOSTRADOR">Mostrador</option></select></div>
      <div class="field"><label for="sf-method">Método</label><select id="sf-method" name="method" class="select"><option value="">Todos</option>
        <option value="ONLINE">Pago online</option><option value="YAPE">Yape</option><option value="PLIN">Plin</option><option value="EFECTIVO">Efectivo</option><option value="LOCAL">Pago en local</option></select></div>
      <div class="field"><label for="sf-client">Cliente</label><input id="sf-client" name="client" type="search" class="input" maxlength="60" placeholder="Nombre o teléfono"></div>
      <div class="field"><label for="sf-from">Desde</label><input id="sf-from" name="date_from" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
      <div class="field"><label for="sf-to">Hasta</label><input id="sf-to" name="date_to" type="date" class="input" min="2000-01-01" max="2099-12-31"></div>
    </form><div id="st"></div></div>`);
  const table = $('#st', root);
  const load = async () => {
    render(table, loading());
    if (state.date_from && state.date_to && state.date_from > state.date_to) {
      render(table, emptyState('fa-calendar-xmark', 'La fecha "Desde" no puede ser posterior a "Hasta".'));
      return;
    }
    try {
      const res = await api.get('/sales', state);
      render(table, res.items.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Comprobante</th><th>Fecha</th><th>Cliente</th>
        <th>Canal</th><th>Método</th><th>Estado</th><th class="text-right">Total</th><th class="text-right">Acciones</th></tr></thead>
        <tbody>${res.items.map((s) => html`<tr><td data-label="Comprobante" class="bold">${s.receipt_code}</td><td data-label="Fecha">${fmtDateTime(s.created_at)}</td>
          <td data-label="Cliente">${s.client ? s.client.full_name : 'Cliente varios'}</td><td data-label="Canal">${s.channel === 'ONLINE' ? 'Online' : 'Mostrador'}</td>
          <td data-label="Método">${s.payment_method_name}</td><td data-label="Estado">${statusBadge(s.status)}</td><td data-label="Total" class="text-right bold">${money(s.total)}</td>
          <td data-label="" class="cell-actions">${s.status === 'PENDIENTE_PAGO' ? html`<button type="button" class="btn btn-gold btn-xs" data-pay="${s.id}">Cobrar</button>` : ''}
            <button type="button" class="btn btn-dark btn-xs" data-view="${s.id}">Detalle</button></td></tr>`)}</tbody></table></div>
        ${pagination(res.page, res.page_size, res.total)}` : emptyState('fa-receipt', 'No hay ventas con esos filtros.'));
      table._items = res.items;
    } catch (err) { render(table, emptyState('fa-triangle-exclamation', err.message)); }
  };
  table.addEventListener('click', (e) => {
    const v = e.target.closest('[data-view]');
    const p = e.target.closest('[data-pay]');
    const pg = e.target.closest('[data-page]');
    if (v) openSaleDetail(Number(v.dataset.view), load);
    if (p) openConfirmPayment(table._items.find((s) => s.id === Number(p.dataset.pay)), load);
    if (pg && !pg.disabled) { state.page = Number(pg.dataset.page); load(); }
  });
  const f = $('#sf', root);
  const apply = () => { Object.assign(state, formValues(f), { page: 1 }); load(); };
  f.addEventListener('change', apply);
  f.addEventListener('input', debounce((e) => { if (e.target.name === 'client') apply(); }, 350));
  f.addEventListener('submit', (e) => e.preventDefault());
  await load();
  if (params[0]) openSaleDetail(Number(params[0]), load);
}
