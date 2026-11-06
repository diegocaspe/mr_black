import { api } from '../../api.js';
import { openProductDetail } from '../../components/product-detail.js';
import {
  $, confirmDialog, emptyState, fmtDateTime, formValues, html, loading, money, openModal, raw, render, submitWith, toast, toastError,
} from '../../ui.js';
import { liveValidate, rules, validateForm } from '../../validators.js';
import { options } from '../shared.js';

const TYPE_LABEL = { ENTRADA: 'Entrada', SALIDA: 'Salida', AJUSTE: 'Ajuste', VENTA: 'Venta', DEVOLUCION: 'Devolución' };

export const stockBadge = (p) => (p.stock === 0 ? html`<span class="badge b-danger">Agotado</span>`
  : p.stock <= p.min_stock ? html`<span class="badge b-warn">Stock bajo</span>` : html`<span class="badge b-ok">OK</span>`);

export function openMovementForm(products, preselect, onSaved) {
  const form = document.createElement('form');
  form.noValidate = true;
  render(form, html`<div class="form-grid">
    <div class="field full"><label for="mv-product">Producto <span class="req">*</span></label>
      <select id="mv-product" name="product_id" class="select" required><option value="">Seleccionar…</option>
      ${options(products, preselect, 'id', (p) => `${p.name} (stock ${p.stock})`)}</select></div>
    <div class="field full"><span class="label">Tipo de movimiento</span>
      <div class="choice-grid mt-1">${[['ENTRADA', 'fa-arrow-down', 'Ingreso de mercadería'], ['SALIDA', 'fa-arrow-up', 'Merma, uso interno, vencido'], ['AJUSTE', 'fa-scale-balanced', 'Conteo físico (stock final)']].map(([v, i, d], idx) => html`
        <label class="choice"><input type="radio" name="movement_type" value="${v}" ${idx === 0 ? raw('checked') : ''}>
        <span class="choice-icon"><i class="fa-solid ${i}" aria-hidden="true"></i></span><span><span class="bold">${TYPE_LABEL[v]}</span><br><span class="xs muted">${d}</span></span></label>`)}</div></div>
    <div class="field"><label for="mv-qty" id="mv-qty-label">Cantidad <span class="req">*</span></label>
      <input id="mv-qty" name="quantity" type="number" class="input" min="0" max="100000" inputmode="numeric" required>
      <p class="field-hint" id="mv-hint"></p></div>
    <div class="field"><label for="mv-reason">Motivo</label><input id="mv-reason" name="reason" class="input" maxlength="200" placeholder="Obligatorio en salidas y ajustes"></div>
  </div>
  <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
    <button type="submit" class="btn btn-gold"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> Registrar movimiento</button></div>`);
  const m = openModal({ title: 'Movimiento de inventario', kicker: 'Inventario', body: form });
  const hint = $('#mv-hint', form);
  const updateHint = () => {
    const p = products.find((x) => x.id === Number(form.elements.product_id.value));
    const type = form.elements.movement_type.value;
    $('#mv-qty-label', form).firstChild.textContent = type === 'AJUSTE' ? 'Stock contado ' : 'Cantidad ';
    hint.textContent = p ? (type === 'SALIDA' ? `Máximo ${p.stock} unidades.` : `Stock actual: ${p.stock}.`) : '';
    if (p && type === 'SALIDA') form.elements.quantity.max = String(p.stock);
    else form.elements.quantity.max = '100000';
  };
  form.addEventListener('change', updateHint);
  updateHint();
  const schema = {
    product_id: [rules.required('Selecciona un producto.')],
    quantity: [rules.intRange(0, 100000, 'La cantidad'), (v, f) => {
      const type = f.elements.movement_type.value;
      const p = products.find((x) => x.id === Number(f.elements.product_id.value));
      if (type !== 'AJUSTE' && Number(v) <= 0) return 'La cantidad debe ser mayor a 0.';
      if (type === 'SALIDA' && p && Number(v) > p.stock) return `Stock insuficiente: quedan ${p.stock} unidades.`;
      return null;
    }],
    reason: [(v, f) => (f.elements.movement_type.value !== 'ENTRADA' && !v.trim() ? 'Indica el motivo de la salida o ajuste.' : null)],
  };
  liveValidate(form, schema);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    const v = formValues(form);
    try {
      const mv = await submitWith(form, form.querySelector('[type=submit]'), () => api.post('/inventory/movements', {
        product_id: Number(v.product_id), movement_type: v.movement_type, quantity: Number(v.quantity), reason: v.reason.trim() || null,
      }));
      m.close();
      toast(`Movimiento registrado. Stock de ${mv.product.name}: ${mv.stock_before} → ${mv.stock_after}.`);
      onSaved?.();
    } catch { /* mostrado */ }
  });
}

export default async function inventoryView(root, { user }) {
  const isAdmin = user.role === 'ADMIN';
  let tab = 'alertas';
  render(root, html`<div class="page-head"><div><h2>Inventario</h2><p>Stock actual, alertas, entradas, salidas y ajustes.</p></div>
      ${isAdmin ? html`<div class="flex gap-2 wrap"><button type="button" class="btn btn-dark" data-bulk><i class="fa-solid fa-sliders" aria-hidden="true"></i> Mínimo para todos</button>
        <button type="button" class="btn btn-gold" data-move><i class="fa-solid fa-right-left" aria-hidden="true"></i> Registrar movimiento</button></div>` : ''}</div>
    <div id="inv-kpis" class="kpis"></div>
    <div class="panel mt-6"><div class="tabs panel-pad" role="tablist" style="margin:0;padding-bottom:0">
      <button class="tab" role="tab" data-tab="alertas" aria-selected="true">Alertas</button>
      <button class="tab" role="tab" data-tab="stock" aria-selected="false">Stock por producto</button>
      <button class="tab" role="tab" data-tab="movimientos" aria-selected="false">Movimientos</button></div>
      <div id="inv-body"></div></div>`);
  let products = [];

  async function loadKpis() {
    try {
      const s = await api.get('/inventory/summary');
      render($('#inv-kpis', root), html`
        <div class="panel kpi"><div><div class="kpi-label">Productos activos</div><div class="kpi-value">${s.active_products}</div><div class="kpi-sub">${s.inactive_products} dado(s) de baja</div></div><span class="kpi-icon"><i class="fa-solid fa-box"></i></span></div>
        <div class="panel kpi ${s.low_stock ? 'alert' : ''}"><div><div class="kpi-label">Stock bajo</div><div class="kpi-value">${s.low_stock}</div><div class="kpi-sub">En o bajo el mínimo</div></div><span class="kpi-icon"><i class="fa-solid fa-triangle-exclamation"></i></span></div>
        <div class="panel kpi ${s.out_of_stock ? 'alert' : ''}"><div><div class="kpi-label">Agotados</div><div class="kpi-value">${s.out_of_stock}</div><div class="kpi-sub">Activos sin stock</div></div><span class="kpi-icon"><i class="fa-solid fa-ban"></i></span></div>
        <div class="panel kpi"><div><div class="kpi-label">Valor del inventario</div><div class="kpi-value">${money(s.inventory_value)}</div><div class="kpi-sub">A precio de venta</div></div><span class="kpi-icon"><i class="fa-solid fa-sack-dollar"></i></span></div>`);
    } catch (err) { toastError(err); }
  }

  async function loadTab() {
    const body = $('#inv-body', root);
    render(body, loading());
    root.querySelectorAll('[data-tab]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.tab === tab)));
    try {
      products = await api.get('/admin/products');
      if (tab === 'alertas' || tab === 'stock') {
        const list = tab === 'alertas' ? products.filter((p) => p.is_active && p.stock <= p.min_stock) : products;
        render(body, list.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Producto</th><th>Categoría</th>
          <th class="text-right">Stock</th><th class="text-right">Mínimo</th><th>Estado</th><th class="text-right">Acciones</th></tr></thead>
          <tbody>${list.map((p) => html`<tr style="${p.is_active ? '' : 'opacity:.55'}"><td data-label="Producto"><span class="bold">${p.name}</span>${p.is_active ? '' : html` <span class="badge badge-plain b-muted">Dado de baja</span>`}</td>
            <td data-label="Categoría">${p.category.name}</td><td data-label="Stock" class="text-right bold">${p.stock}</td><td data-label="Mínimo" class="text-right">${p.min_stock}</td>
            <td data-label="Estado">${stockBadge(p)}</td><td data-label="" class="cell-actions">
              <button type="button" class="btn btn-dark btn-xs" data-photos="${p.id}"><i class="fa-solid fa-camera" aria-hidden="true"></i> Fotos${p.images.length ? ` (${p.images.length})` : ''}</button>
              ${isAdmin ? html`<button type="button" class="btn btn-dark btn-xs" data-move-product="${p.id}">Movimiento</button>` : ''}</td></tr>`)}</tbody></table></div>`
          : emptyState('fa-circle-check', tab === 'alertas' ? 'No hay productos en o bajo su stock mínimo.' : 'No hay productos.'));
      } else {
        const mv = await api.get('/inventory/movements');
        render(body, mv.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha</th><th>Producto</th><th>Tipo</th>
          <th class="text-right">Cantidad</th><th class="text-right">Stock</th><th>Motivo</th><th>Usuario</th></tr></thead>
          <tbody>${mv.map((m) => html`<tr><td data-label="Fecha">${fmtDateTime(m.created_at)}</td><td data-label="Producto">${m.product.name}</td>
            <td data-label="Tipo"><span class="badge ${m.quantity > 0 ? 'b-ok' : 'b-warn'}">${TYPE_LABEL[m.movement_type]}</span></td>
            <td data-label="Cantidad" class="text-right bold">${m.quantity > 0 ? `+${m.quantity}` : m.quantity}</td>
            <td data-label="Stock" class="text-right">${m.stock_before} → ${m.stock_after}</td><td data-label="Motivo">${m.reason || '—'}</td>
            <td data-label="Usuario">${m.user ? m.user.full_name : '—'}</td></tr>`)}</tbody></table></div>` : emptyState('fa-right-left', 'Sin movimientos.'));
      }
    } catch (err) { render(body, emptyState('fa-triangle-exclamation', err.message)); }
  }

  const refresh = () => { loadKpis(); loadTab(); };
  root.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-tab]');
    if (t) { tab = t.dataset.tab; loadTab(); return; }
    if (e.target.closest('[data-move]')) openMovementForm(products.filter((p) => p.is_active), null, refresh);
    const ph = e.target.closest('[data-photos]');
    if (ph) { openProductDetail(Number(ph.dataset.photos), { staffView: true, onChange: loadTab }); return; }
    const mp = e.target.closest('[data-move-product]');
    if (mp) openMovementForm(products, Number(mp.dataset.moveProduct), refresh);
    if (e.target.closest('[data-bulk]')) openBulk(refresh);
  });
  refresh();
}

async function openBulk(refresh) {
  const settings = await api.get('/settings').catch(() => ({ inventory: { default_min_stock: 3 } }));
  const form = document.createElement('form');
  form.noValidate = true;
  render(form, html`<p class="muted small">Aplica el mismo stock mínimo a todos los productos. Las alertas y el resaltado se recalculan inmediatamente.</p>
    <div class="field mt-4"><label for="bulk-min">Stock mínimo <span class="req">*</span></label>
      <input id="bulk-min" name="min_stock" type="number" class="input" min="0" max="100000" value="${settings.inventory.default_min_stock}" required></div>
    <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button><button type="submit" class="btn btn-gold">Aplicar</button></div>`);
  const m = openModal({ title: 'Stock mínimo para todos', body: form, size: 'sm' });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, { min_stock: [rules.intRange(0, 100000, 'El mínimo')] })) return;
    const ok = await confirmDialog({ title: '¿Aplicar a todos los productos?', message: 'Se reemplazará el stock mínimo individual de cada producto.', confirmText: 'Aplicar' });
    if (!ok) return;
    try {
      const res = await submitWith(form, form.querySelector('[type=submit]'), () => api.post('/inventory/min-stock', { min_stock: Number(form.elements.min_stock.value) }));
      m.close();
      toast(res.message);
      refresh();
    } catch { /* mostrado */ }
  });
}
