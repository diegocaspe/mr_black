import { api } from '../../api.js';
import { mountPaymentSelector, paymentPayload, paymentSchema } from '../../components/cart.js';
import {
  $, clearFieldError, emptyState, fmtDateTime, formValues, html, money, raw, render, setFieldError, statusBadge, submitWith,
  toast,
} from '../../ui.js';
import { validateForm } from '../../validators.js';
import { openSaleDetail, options } from '../shared.js';

export default async function counterView(root) {
  const [productsAll, clients, methods] = await Promise.all([
    api.get('/admin/products', { active: true }), api.get('/clients'), api.get('/payments/methods'),
  ]);
  const products = productsAll.filter((p) => p.is_active);
  const lines = []; // { product_id, quantity }

  render(root, html`<div class="page-head"><div><h2>Venta de mostrador</h2><p>La venta descuenta stock, registra el pago y genera el comprobante.</p></div></div>
    <div class="grid" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);align-items:start" data-layout>
      <form class="panel panel-pad" id="sale-form" novalidate>
        <div class="form-grid">
          <div class="field full"><label for="s-client">Cliente</label>
            <select id="s-client" name="client_id" class="select"><option value="">Cliente varios (sin registrar)</option>
            ${options(clients, null, 'id', (c) => `${c.full_name} · ${c.phone}`)}</select></div>
          <div class="field"><label for="s-product">Producto</label>
            <select id="s-product" name="product" class="select"><option value="">Seleccionar…</option>
            ${products.map((p) => html`<option value="${p.id}" ${p.stock <= 0 ? raw('disabled') : ''}>${p.name} · ${money(p.price)} · ${p.stock > 0 ? `stock ${p.stock}` : 'agotado'}</option>`)}</select></div>
          <div class="field"><label for="s-qty">Cantidad</label>
            <div class="flex gap-2"><input id="s-qty" name="qty" type="number" class="input" min="1" value="1" inputmode="numeric">
            <button type="button" class="btn btn-dark" data-add><i class="fa-solid fa-plus" aria-hidden="true"></i> Agregar</button></div>
            <p class="field-hint" id="s-qty-hint"></p></div>
        </div>
        <div class="mt-4" id="s-lines"></div>
        <div class="mt-5" data-pay-methods></div>
        <div class="pay-panel" data-pay-fields></div>
        <div class="field mt-4"><label for="s-notes">Nota (opcional)</label><input id="s-notes" name="notes" class="input" maxlength="300"></div>
        <button type="submit" class="btn btn-gold btn-block mt-5" id="s-submit" disabled><i class="fa-solid fa-cash-register" aria-hidden="true"></i> Registrar venta</button>
      </form>
      <section class="panel"><div class="panel-head"><h3 class="panel-title">Últimas ventas</h3><a href="#/ventas" class="small">Ver todas</a></div>
        <div id="recent" class="panel-pad"></div></section>
    </div>`);
  const layout = root.querySelector('[data-layout]');
  const mq = window.matchMedia('(max-width: 1100px)');
  const apply = () => { layout.style.gridTemplateColumns = mq.matches ? '1fr' : 'minmax(0,1.3fr) minmax(0,1fr)'; };
  mq.addEventListener('change', apply);
  apply();

  const form = $('#sale-form', root);
  mountPaymentSelector(form, methods.filter((m) => m.counter_allowed));
  const productSel = form.elements.product;
  const qtyInput = form.elements.qty;
  const hint = $('#s-qty-hint', root);
  const byId = (id) => products.find((p) => p.id === Number(id));
  const inCart = (id) => lines.find((l) => l.product_id === Number(id))?.quantity || 0;

  productSel.addEventListener('change', () => {
    const p = byId(productSel.value);
    clearFieldError(qtyInput);
    if (!p) { hint.textContent = ''; return; }
    const remaining = p.stock - inCart(p.id);
    qtyInput.max = String(Math.max(1, remaining));
    hint.textContent = `Disponible: ${remaining} unidad(es).`;
  });

  function drawLines() {
    const total = lines.reduce((s, l) => s + Number(byId(l.product_id).price) * l.quantity, 0);
    render($('#s-lines', root), lines.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Producto</th><th class="text-right">Cant.</th><th class="text-right">Importe</th><th></th></tr></thead>
      <tbody>${lines.map((l) => { const p = byId(l.product_id); return html`<tr><td data-label="Producto">${p.name}<br><span class="xs faint">${money(p.price)} c/u</span></td>
        <td data-label="Cant." class="text-right">${l.quantity}</td><td data-label="Importe" class="text-right">${money(Number(p.price) * l.quantity)}</td>
        <td data-label="" class="cell-actions"><button type="button" class="btn btn-ghost btn-xs" data-remove="${p.id}" aria-label="Quitar ${p.name}"><i class="fa-solid fa-trash"></i></button></td></tr>`; })}</tbody></table></div>
      <div class="summary-row mt-2"><span class="bold" style="color:#fff">Total</span><b class="gold" style="font-size:1.2rem">${money(total)}</b></div>`
      : html`<div class="empty" style="padding:24px"><i class="fa-solid fa-basket-shopping" aria-hidden="true"></i>Agrega productos a la venta.</div>`);
    $('#s-submit', root).disabled = !lines.length || total <= 0;
  }

  root.querySelector('[data-add]').addEventListener('click', () => {
    clearFieldError(qtyInput);
    const p = byId(productSel.value);
    if (!p) { setFieldError(form, 'product', 'Selecciona un producto.'); return; }
    const qty = Number(qtyInput.value);
    if (!Number.isInteger(qty) || qty < 1) { setFieldError(form, 'qty', 'La cantidad debe ser un entero mayor a 0.'); return; }
    const remaining = p.stock - inCart(p.id);
    if (qty > remaining) {
      // 0024820: aviso explícito y cantidad limitada al stock disponible.
      setFieldError(form, 'qty', remaining > 0 ? `Stock insuficiente: quedan ${remaining} unidades.` : `${p.name} no tiene más stock disponible.`);
      qtyInput.value = String(Math.max(1, remaining));
      return;
    }
    const line = lines.find((l) => l.product_id === p.id);
    if (line) line.quantity += qty; else lines.push({ product_id: p.id, quantity: qty });
    qtyInput.value = '1';
    productSel.dispatchEvent(new Event('change'));
    drawLines();
  });
  $('#s-lines', root).addEventListener('click', (e) => {
    const b = e.target.closest('[data-remove]');
    if (!b) return;
    lines.splice(lines.findIndex((l) => l.product_id === Number(b.dataset.remove)), 1);
    productSel.dispatchEvent(new Event('change'));
    drawLines();
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const method = form.elements.payment_method.value;
    if (!lines.length || !validateForm(form, paymentSchema(method))) return;
    const v = formValues(form);
    try {
      const sale = await submitWith(form, $('#s-submit', root), () => api.post('/sales', {
        client_id: v.client_id ? Number(v.client_id) : null, items: lines, payment_method: method,
        payment: paymentPayload(v), notes: v.notes.trim() || null,
      }));
      toast(`Venta registrada · ${sale.receipt_code}`);
      openSaleDetail(sale.id, null, sale.change_due);
      // Recarga stock real desde el servidor.
      const fresh = await api.get('/admin/products', { active: true });
      products.splice(0, products.length, ...fresh.filter((p) => p.is_active));
      lines.length = 0;
      render(productSel, html`<option value="">Seleccionar…</option>${products.map((p) => html`<option value="${p.id}" ${p.stock <= 0 ? raw('disabled') : ''}>${p.name} · ${money(p.price)} · ${p.stock > 0 ? `stock ${p.stock}` : 'agotado'}</option>`)}`);
      form.reset();
      mountPaymentSelector(form, methods.filter((m) => m.counter_allowed));
      hint.textContent = '';
      drawLines();
      loadRecent();
    } catch { /* mostrado en el formulario */ }
  });

  async function loadRecent() {
    const box = $('#recent', root);
    try {
      const res = await api.get('/sales', { page_size: 8 });
      render(box, res.items.length ? html`${res.items.map((s) => html`<button type="button" class="list-row" data-sale="${s.id}" style="width:100%;background:none;border-left:0;border-right:0;border-top:0;text-align:left">
        <div><div class="bold">${money(s.total)} <span class="xs faint">· ${s.receipt_code}</span></div>
        <div class="xs faint">${s.client ? s.client.full_name : 'Cliente varios'} · ${fmtDateTime(s.created_at)}</div></div>${statusBadge(s.status)}</button>`)}`
        : emptyState('fa-receipt', 'Aún no hay ventas.'));
    } catch (err) { render(box, emptyState('fa-triangle-exclamation', err.message)); }
  }
  $('#recent', root).addEventListener('click', (e) => {
    const b = e.target.closest('[data-sale]');
    if (b) openSaleDetail(Number(b.dataset.sale), loadRecent);
  });
  drawLines();
  loadRecent();
}
