import { api } from '../../api.js';
import { openProductDetail } from '../../components/product-detail.js';
import {
  $, confirmDialog, debounce, emptyState, formValues, html, loading, money, openModal, productCover, raw, render, submitWith, toast,
  toastError,
} from '../../ui.js';
import { liveValidate, rules, validateForm } from '../../validators.js';
import { options } from '../shared.js';
import { openMovementForm, stockBadge } from './inventory.js';

function openProductForm(product, categories, onSaved) {
  const isNew = !product;
  const p = product || { name: '', description: '', category: { id: '' }, price: '', image_url: '', icon: 'fa-box', min_stock: 3, is_active: true };
  const form = document.createElement('form');
  form.noValidate = true;
  form.autocomplete = 'off';
  render(form, html`<div class="form-grid">
    <div class="field full"><label for="pf-name">Nombre <span class="req">*</span></label>
      <input id="pf-name" name="name" class="input" maxlength="60" required value="${p.name}">
      <p class="field-hint">3 a 60 caracteres: letras, números, espacios, guion y punto.</p></div>
    <div class="field"><label for="pf-cat">Categoría <span class="req">*</span></label>
      <select id="pf-cat" name="category_id" class="select" required><option value="">Seleccionar…</option>${options(categories, p.category.id)}</select>
      ${categories.length ? '' : html`<p class="field-hint">Aún no hay categorías. Créalas con el botón «Categorías» de esta página.</p>`}</div>
    <div class="field"><label for="pf-price">Precio (S/) <span class="req">*</span></label>
      <input id="pf-price" name="price" class="input" inputmode="decimal" maxlength="9" placeholder="0.00" required value="${p.price}">
      <p class="field-hint">Mínimo S/ 0.10, máximo 2 decimales.</p></div>
    ${isNew ? html`<div class="field"><label for="pf-stock">Stock inicial <span class="req">*</span></label>
      <input id="pf-stock" name="initial_stock" type="number" class="input" min="0" max="100000" value="0" required></div>`
      : html`<div class="field"><span class="label">Stock actual</span><div class="input" style="display:flex;align-items:center;justify-content:space-between">
        <b>${p.stock}</b><button type="button" class="btn btn-ghost btn-xs" data-adjust>Registrar movimiento</button></div>
        <p class="field-hint">El stock cambia mediante movimientos de inventario (queda historial).</p></div>`}
    <div class="field"><label for="pf-min">Stock mínimo <span class="req">*</span></label>
      <input id="pf-min" name="min_stock" type="number" class="input" min="0" max="100000" required value="${p.min_stock}"></div>
    <div class="field"><label for="pf-icon">Ícono (Font Awesome)</label>
      <input id="pf-icon" name="icon" class="input" maxlength="33" value="${p.icon}" placeholder="fa-box"></div>
    <div class="field full"><label for="pf-img">URL de imagen</label>
      <input id="pf-img" name="image_url" class="input" type="url" maxlength="500" value="${p.image_url || ''}" placeholder="https://…"></div>
    <div class="field full"><label for="pf-desc">Descripción</label>
      <textarea id="pf-desc" name="description" class="textarea" rows="2" maxlength="500">${p.description || ''}</textarea></div>
    <div class="full"><label class="switch"><input type="checkbox" name="is_active" ${p.is_active ? raw('checked') : ''}> <span>Activo (visible en la tienda)</span></label></div>
  </div>
  <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
    <button type="submit" class="btn btn-gold"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> Guardar</button></div>`);
  const m = openModal({ title: isNew ? 'Agregar producto' : 'Editar producto', kicker: 'Productos', body: form, size: 'lg' });
  form.querySelector('[data-adjust]')?.addEventListener('click', () => { m.close(); openMovementForm([product], product.id, onSaved); });
  const schema = {
    name: [rules.productName],
    category_id: [rules.required('Selecciona una categoría.')],
    price: [rules.price],
    min_stock: [rules.intRange(0, 100000, 'El stock mínimo')],
    icon: [(v) => (/^fa-[a-z0-9-]{1,30}$/.test(v.trim()) ? null : 'Usa un nombre de ícono como fa-box.')],
    image_url: [rules.imageUrl],
    description: [rules.maxLen(500)],
    ...(isNew ? { initial_stock: [rules.intRange(0, 100000, 'El stock inicial')] } : {}),
  };
  liveValidate(form, schema);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    const v = formValues(form);
    const body = {
      name: v.name, description: v.description.trim() || null, category_id: Number(v.category_id), price: v.price.trim(),
      image_url: v.image_url.trim() || null, icon: v.icon.trim() || 'fa-box', min_stock: Number(v.min_stock), is_active: v.is_active,
    };
    if (isNew) body.initial_stock = Number(v.initial_stock);
    try {
      const saved = await submitWith(form, form.querySelector('[type=submit]'),
        () => (isNew ? api.post('/admin/products', body) : api.put(`/admin/products/${product.id}`, body)));
      m.close();
      toast(isNew ? `Producto "${saved.name}" creado.` : `Producto "${saved.name}" actualizado.`);
      onSaved?.();
    } catch { /* mostrado por campo */ }
  });
}

function openCategories(onChange) {
  const box = document.createElement('div');
  const m = openModal({ title: 'Categorías', kicker: 'Productos', body: box });
  const draw = async () => {
    const cats = await api.get('/categories/all');
    render(box, html`<form id="cat-form" class="flex gap-2 items-start" novalidate>
        <div class="field grow"><label for="cat-name" class="sr-only">Nueva categoría</label><input id="cat-name" name="name" class="input" maxlength="40" placeholder="Nueva categoría"></div>
        <button type="submit" class="btn btn-gold">Agregar</button></form>
      <div class="mt-4">${cats.map((c) => html`<div class="list-row"><span>${c.name} ${c.is_active ? '' : html`<span class="badge badge-plain b-muted">Inactiva</span>`}</span>
        <button type="button" class="btn btn-dark btn-xs" data-toggle-cat="${c.id}" data-name="${c.name}" data-active="${c.is_active}">${c.is_active ? 'Desactivar' : 'Activar'}</button></div>`)}</div>`);
    const f = $('#cat-form', box);
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!validateForm(f, { name: [(v) => (/^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+( [A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+)*$/.test(v.trim()) && v.trim().length >= 3 ? null : 'Entre 3 y 40 caracteres: letras, números y espacios.')] })) return;
      try {
        await submitWith(f, f.querySelector('[type=submit]'), () => api.post('/categories', { name: f.elements.name.value.trim() }));
        toast('Categoría creada.');
        draw(); onChange();
      } catch { /* mostrado */ }
    });
  };
  box.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-toggle-cat]');
    if (!b) return;
    try {
      await api.put(`/categories/${b.dataset.toggleCat}`, { name: b.dataset.name, is_active: b.dataset.active !== 'true' });
      toast('Categoría actualizada.');
      draw(); onChange();
    } catch (err) { toastError(err); }
  });
  draw().catch((err) => { m.close(); toastError(err); });
}

export default async function productsView(root) {
  let categories = await api.get('/categories/all');
  const state = { q: '', category_id: '', active: '', stock: '' };
  render(root, html`<div class="page-head"><div><h2>Productos</h2><p>Catálogo, precios, stock mínimo y baja lógica.</p></div>
      <div class="flex gap-2 wrap"><button type="button" class="btn btn-dark" data-cats><i class="fa-solid fa-tags" aria-hidden="true"></i> Categorías</button>
      <button type="button" class="btn btn-gold" data-new><i class="fa-solid fa-plus" aria-hidden="true"></i> Agregar producto</button></div></div>
    <div class="panel"><form class="filters panel-pad" id="pf" style="border-bottom:1px solid var(--line)">
      <div class="field"><label for="pf-q">Buscar</label><input id="pf-q" name="q" type="search" class="input" maxlength="60" placeholder="Nombre o descripción"></div>
      <div class="field"><label for="pf-c">Categoría</label><select id="pf-c" name="category_id" class="select"><option value="">Todas</option>${options(categories)}</select></div>
      <div class="field"><label for="pf-a">Estado</label><select id="pf-a" name="active" class="select"><option value="">Todos</option><option value="true">Activos</option><option value="false">Dados de baja</option></select></div>
      <div class="field"><label for="pf-s">Stock</label><select id="pf-s" name="stock" class="select"><option value="">Todos</option><option value="alerta">En alerta</option><option value="bajo">Bajo</option><option value="agotado">Agotado</option></select></div>
    </form><div id="pt"></div></div>`);
  const table = $('#pt', root);
  let rows = [];
  const load = async () => {
    render(table, loading());
    try {
      rows = await api.get('/admin/products', state);
      render(table, rows.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Producto</th><th>Categoría</th><th class="text-right">Precio</th>
        <th class="text-right">Stock</th><th class="text-right">Mínimo</th><th>Alerta</th><th>Estado</th><th class="text-right">Acciones</th></tr></thead>
        <tbody>${rows.map((p) => html`<tr style="${p.is_active ? '' : 'opacity:.6'}${p.is_active && p.stock <= p.min_stock ? ';background:#221c0d' : ''}">
          <td data-label="Producto"><span class="flex items-center gap-2"><span class="thumb" style="width:36px;height:36px;font-size:1rem">${productCover(p) ? html`<img src="${productCover(p)}" alt="">` : html`<i class="fa-solid ${p.icon}" aria-hidden="true"></i>`}</span><span class="bold">${p.name}</span></span></td>
          <td data-label="Categoría">${p.category.name}</td><td data-label="Precio" class="text-right">${money(p.price)}</td>
          <td data-label="Stock" class="text-right bold">${p.stock}</td><td data-label="Mínimo" class="text-right">${p.min_stock}</td>
          <td data-label="Alerta">${stockBadge(p)}</td>
          <td data-label="Estado">${p.is_active ? html`<span class="badge b-ok">Activo</span>` : html`<span class="badge b-danger">Dado de baja</span>`}</td>
          <td data-label="" class="cell-actions"><button type="button" class="btn btn-dark btn-xs" data-photos="${p.id}"><i class="fa-solid fa-camera" aria-hidden="true"></i> Fotos${p.images.length ? ` (${p.images.length})` : ''}</button>
            <button type="button" class="btn btn-dark btn-xs" data-edit="${p.id}"><i class="fa-solid fa-pen" aria-hidden="true"></i> Editar</button>
            <button type="button" class="btn btn-xs ${p.is_active ? 'btn-danger' : 'btn-gold'}" data-toggle="${p.id}">${p.is_active ? 'Dar de baja' : 'Activar'}</button></td></tr>`)}</tbody></table></div>`
        : emptyState('fa-box-open', 'No hay productos con esos filtros.'));
    } catch (err) { render(table, emptyState('fa-triangle-exclamation', err.message)); }
  };
  table.addEventListener('click', async (e) => {
    const ph = e.target.closest('[data-photos]');
    if (ph) { openProductDetail(Number(ph.dataset.photos), { staffView: true, onChange: load }); return; }
    const ed = e.target.closest('[data-edit]');
    const tg = e.target.closest('[data-toggle]');
    if (ed) openProductForm(rows.find((p) => p.id === Number(ed.dataset.edit)), categories, load);
    if (tg) {
      const p = rows.find((x) => x.id === Number(tg.dataset.toggle));
      const activate = !p.is_active;
      const ok = await confirmDialog({
        title: activate ? `¿Activar "${p.name}"?` : `¿Dar de baja "${p.name}"?`,
        message: activate ? 'Volverá a mostrarse en la tienda pública.' : 'Dejará de mostrarse en la tienda y no podrá agregarse al carrito. Podrás reactivarlo.',
        confirmText: activate ? 'Activar' : 'Dar de baja', danger: !activate,
      });
      if (!ok) return;
      try {
        const saved = await api.patch(`/admin/products/${p.id}/status`, { is_active: activate });
        // Éxito solo si el servidor confirma el nuevo estado persistido.
        if (saved.is_active !== activate) throw new Error('No se pudo actualizar el estado del producto.');
        toast(saved.is_active ? 'Producto activado.' : 'Producto dado de baja.');
        load();
      } catch (err) { toastError(err); load(); }
    }
  });
  const f = $('#pf', root);
  const apply = () => { Object.assign(state, formValues(f)); load(); };
  f.addEventListener('change', apply);
  f.addEventListener('input', debounce((e) => { if (e.target.name === 'q') apply(); }, 350));
  f.addEventListener('submit', (e) => e.preventDefault());
  root.querySelector('[data-new]').addEventListener('click', () => openProductForm(null, categories.filter((c) => c.is_active), load));
  root.querySelector('[data-cats]').addEventListener('click', () => openCategories(async () => { categories = await api.get('/categories/all'); }));
  load();
}
