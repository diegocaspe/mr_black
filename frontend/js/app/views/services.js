import { api } from '../../api.js';
import { openServiceDetail } from '../../components/service-detail.js';
import { emptyState, formValues, html, loading, money, openModal, raw, render, submitWith, toast, toastError } from '../../ui.js';
import { liveValidate, rules, validateForm } from '../../validators.js';

function openServiceForm(s, onSaved) {
  const form = document.createElement('form');
  form.noValidate = true;
  const v = s || { name: '', description: '', price: '', duration_minutes: 30, icon: 'fa-scissors', is_active: true };
  render(form, html`<div class="form-grid">
    <div class="field full"><label for="sv-name">Nombre <span class="req">*</span></label><input id="sv-name" name="name" class="input" maxlength="50" required value="${v.name}"></div>
    <div class="field"><label for="sv-price">Precio (S/) <span class="req">*</span></label><input id="sv-price" name="price" class="input" inputmode="decimal" maxlength="9" required value="${v.price}"></div>
    <div class="field"><label for="sv-dur">Duración (min) <span class="req">*</span></label><input id="sv-dur" name="duration_minutes" type="number" class="input" min="5" max="480" step="5" required value="${v.duration_minutes}"></div>
    <div class="field"><label for="sv-icon">Ícono</label><input id="sv-icon" name="icon" class="input" maxlength="33" value="${v.icon}"></div>
    <div class="field full"><label for="sv-desc">Descripción</label><textarea id="sv-desc" name="description" class="textarea" rows="2" maxlength="500">${v.description || ''}</textarea></div>
    <div class="full"><label class="switch"><input type="checkbox" name="is_active" ${v.is_active ? raw('checked') : ''}> <span>Activo (disponible para reservar)</span></label></div>
  </div><div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button><button type="submit" class="btn btn-gold">Guardar</button></div>`);
  const m = openModal({ title: s ? 'Editar servicio' : 'Nuevo servicio', kicker: 'Servicios', body: form });
  const schema = {
    name: [(x) => (/^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 +\-]{3,50}$/.test(x.trim()) ? null : 'Entre 3 y 50 caracteres (letras, números, espacios, + y -).')],
    price: [rules.price],
    duration_minutes: [rules.intRange(5, 480, 'La duración'), (x) => (Number(x) % 5 ? 'La duración debe ser múltiplo de 5.' : null)],
    icon: [(x) => (/^fa-[a-z0-9-]{1,30}$/.test(x.trim()) ? null : 'Usa un nombre de ícono como fa-scissors.')],
  };
  liveValidate(form, schema);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    const d = formValues(form);
    const body = { name: d.name, description: d.description.trim() || null, price: d.price.trim(), duration_minutes: Number(d.duration_minutes), icon: d.icon.trim(), is_active: d.is_active };
    try {
      await submitWith(form, form.querySelector('[type=submit]'), () => (s ? api.put(`/services/${s.id}`, body) : api.post('/services', body)));
      m.close();
      toast('Servicio guardado.');
      onSaved();
    } catch { /* mostrado */ }
  });
}

export default async function servicesView(root, { user }) {
  // CAJA gestiona la ficha y las fotos; crear, editar precio/duración y activar siguen siendo de ADMIN.
  const isAdmin = user.role === 'ADMIN';
  render(root, html`<div class="page-head"><div><h2>Servicios</h2><p>${isAdmin ? 'Precios y duración que usa la agenda para calcular disponibilidad.'
    : 'Ficha y fotos de cada servicio. El precio y la duración los define el administrador.'}</p></div>
    ${isAdmin ? html`<button type="button" class="btn btn-gold" data-new><i class="fa-solid fa-plus" aria-hidden="true"></i> Nuevo servicio</button>` : ''}</div><div id="sv"></div>`);
  const box = root.querySelector('#sv');
  let rows = [];
  const load = async () => {
    render(box, loading());
    try {
      rows = await api.get('/services', { all: true });
      render(box, rows.length ? html`<div class="cards">${rows.map((s) => html`<article class="panel service-card" style="${s.is_active ? '' : 'opacity:.6'}">
        <div class="flex justify-between"><div class="service-icon"><i class="fa-solid ${s.icon}" aria-hidden="true"></i></div>
          <span class="badge ${s.is_active ? 'b-ok' : 'b-danger'}">${s.is_active ? 'Activo' : 'Inactivo'}</span></div>
        <h3>${s.name}</h3><p>${s.description || ''}</p>
        <div class="service-meta"><span class="price">${money(s.price)}</span><span class="xs muted">${s.duration_minutes} min</span></div>
        <div class="flex gap-2 mt-4"><button type="button" class="btn btn-dark btn-sm grow" data-sheet="${s.id}"><i class="fa-solid fa-images" aria-hidden="true"></i> Ficha y fotos${s.images.length ? ` (${s.images.length})` : ''}</button></div>
        ${isAdmin ? html`<div class="flex gap-2 mt-2"><button type="button" class="btn btn-dark btn-sm grow" data-edit="${s.id}">Editar</button>
          <button type="button" class="btn btn-sm grow ${s.is_active ? 'btn-danger' : 'btn-gold'}" data-toggle="${s.id}">${s.is_active ? 'Desactivar' : 'Activar'}</button></div>` : ''}
      </article>`)}</div>` : emptyState('fa-scissors', 'No hay servicios.'));
    } catch (err) { render(box, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.addEventListener('click', async (e) => {
    if (e.target.closest('[data-new]')) openServiceForm(null, load);
    const sh = e.target.closest('[data-sheet]');
    if (sh) { openServiceDetail(Number(sh.dataset.sheet), { staffView: true, onChange: load }); return; }
    const ed = e.target.closest('[data-edit]');
    if (ed) openServiceForm(rows.find((s) => s.id === Number(ed.dataset.edit)), load);
    const tg = e.target.closest('[data-toggle]');
    if (tg) {
      const s = rows.find((x) => x.id === Number(tg.dataset.toggle));
      try {
        await api.put(`/services/${s.id}`, { name: s.name, description: s.description, price: s.price, duration_minutes: s.duration_minutes, icon: s.icon, is_active: !s.is_active });
        toast(s.is_active ? 'Servicio desactivado.' : 'Servicio activado.');
        load();
      } catch (err) { toastError(err); }
    }
  });
  load();
}
