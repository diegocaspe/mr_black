import { api } from '../../api.js';
import {
  $, confirmDialog, debounce, emptyState, fmtDateTime, formValues, html, loading, openModal, raw, render, submitWith, toast,
  toastError,
} from '../../ui.js';
import { attachPhoneNormalizer, attachStrengthMeter, liveValidate, rules, validateForm } from '../../validators.js';

const ROLES = [['ADMIN', 'Administrador'], ['CAJA', 'Encargado de caja'], ['BARBERO', 'Barbero'], ['CLIENTE', 'Cliente']];
const ROLE_LABEL = Object.fromEntries(ROLES);

/**
 * Formulario de usuario. Se construye desde cero en cada apertura (0024805): nunca reutiliza
 * valores de un registro anterior y desactiva el autocompletado del navegador.
 */
async function openUserForm(user, me, onSaved) {
  const isNew = !user;
  const barbers = await api.get('/barbers/admin');
  const u = user || { full_name: '', username: '', email: '', role: 'CAJA', is_active: true, barber_id: null, phone: '' };
  const form = document.createElement('form');
  form.noValidate = true;
  form.autocomplete = 'off';
  const self = user && user.id === me.id;
  render(form, html`<div class="form-grid">
    <div class="field full"><label for="uf-name">Nombre completo <span class="req">*</span></label>
      <input id="uf-name" name="full_name" class="input" maxlength="60" autocomplete="off" required value="${u.full_name}"></div>
    <div class="field"><label for="uf-user">Usuario <span class="req">*</span></label>
      <input id="uf-user" name="username" class="input" maxlength="30" autocomplete="off" required value="${u.username}">
      <p class="field-hint">3 a 30: letras, números, punto, guion o guion bajo.</p></div>
    <div class="field"><label for="uf-email">Correo</label>
      <input id="uf-email" name="email" type="email" class="input" maxlength="120" autocomplete="off" value="${u.email || ''}"></div>
    <div class="field"><label for="uf-role">Rol <span class="req">*</span></label>
      <select id="uf-role" name="role" class="select" ${self || u.is_protected ? raw('disabled') : ''}>
        ${ROLES.map(([v, l]) => html`<option value="${v}" ${v === u.role ? raw('selected') : ''}>${l}</option>`)}</select>
      ${self ? html`<p class="field-hint">No puedes cambiar tu propio rol.</p>` : ''}</div>
    <div class="field"><span class="label">Estado ${isNew ? 'inicial' : ''}</span>
      <label class="switch mt-2"><input type="checkbox" name="is_active" ${u.is_active ? raw('checked') : ''} ${self || u.is_protected ? raw('disabled') : ''}>
        <span data-status-label>${u.is_active ? 'Activo' : 'Inactivo'}</span></label></div>
    <div class="field full" data-role-only="BARBERO"><label for="uf-barber">Perfil de barbero</label>
      <select id="uf-barber" name="barber_id" class="select"><option value="">Crear un perfil nuevo con este nombre</option>
        ${barbers.filter((b) => b.is_active && (!b.user_id || b.user_id === user?.id)).map((b) => html`<option value="${b.id}" ${b.id === u.barber_id ? raw('selected') : ''}>${b.full_name}</option>`)}</select>
      <p class="field-hint">El historial de citas del barbero se conserva aunque cambie la cuenta.</p></div>
    <div class="field full" data-role-only="CLIENTE"><label for="uf-phone">Teléfono del cliente <span class="req">*</span></label>
      <input id="uf-phone" name="phone" class="input" inputmode="tel" maxlength="15" placeholder="9XXXXXXXX" value="${u.phone || ''}"></div>
    ${isNew ? html`<div class="field"><label for="uf-pass">Contraseña <span class="req">*</span></label>
        <input id="uf-pass" name="password" type="password" class="input" autocomplete="new-password" maxlength="128" required>
        <div class="strength" id="uf-strength" data-score="0" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
        <p class="field-hint" id="uf-strength-label">Mínimo 8 caracteres con letras y números.</p></div>
      <div class="field"><label for="uf-pass2">Confirmar contraseña <span class="req">*</span></label>
        <input id="uf-pass2" name="password_confirm" type="password" class="input" autocomplete="new-password" maxlength="128" required></div>` : ''}
  </div>
  <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
    <button type="submit" class="btn btn-gold"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> ${isNew ? 'Crear cuenta' : 'Guardar cambios'}</button></div>`);
  form.reset(); // asegura valores por defecto del DOM recién creado
  const m = openModal({ title: isNew ? 'Nueva cuenta' : `Editar usuario`, kicker: 'Usuarios', body: form, size: 'lg' });

  const syncRole = () => {
    const role = form.elements.role.value;
    form.querySelectorAll('[data-role-only]').forEach((el) => { el.hidden = el.dataset.roleOnly !== role; });
  };
  form.elements.role.addEventListener('change', syncRole);
  syncRole();
  form.elements.is_active.addEventListener('change', () => {
    form.querySelector('[data-status-label]').textContent = form.elements.is_active.checked ? 'Activo' : 'Inactivo';
  });
  attachPhoneNormalizer(form.elements.phone);
  if (isNew) attachStrengthMeter(form.elements.password, $('#uf-strength', form), $('#uf-strength-label', form));

  const schema = {
    full_name: [rules.personName],
    username: [rules.username],
    email: [rules.optionalEmail],
    phone: [(v, f) => (f.elements.role.value === 'CLIENTE' ? rules.phone(v) : null)],
    ...(isNew ? {
      password: [rules.password, (v, f) => (f.elements.username.value && v.toLowerCase().includes(f.elements.username.value.trim().toLowerCase()) ? 'La contraseña no debe contener el nombre de usuario.' : null)],
      password_confirm: [rules.required('Confirma la contraseña.'), rules.sameAs('password')],
    } : {}),
  };
  liveValidate(form, schema);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    const v = formValues(form);
    const role = form.elements.role.value;
    const body = {
      full_name: v.full_name, username: v.username.trim().toLowerCase(), email: v.email.trim() || null, role,
      is_active: form.elements.is_active.checked,
      barber_id: role === 'BARBERO' && v.barber_id ? Number(v.barber_id) : null,
      phone: role === 'CLIENTE' ? v.phone : null,
    };
    if (isNew) Object.assign(body, { password: v.password, password_confirm: v.password_confirm });
    if (!isNew && role !== user.role) {
      const ok = await confirmDialog({ title: '¿Cambiar el rol?', message: `La cuenta pasará de ${ROLE_LABEL[user.role]} a ${ROLE_LABEL[role]}. Su historial se conserva.`, confirmText: 'Cambiar rol' });
      if (!ok) return;
    }
    try {
      const saved = await submitWith(form, form.querySelector('[type=submit]'), () => (isNew ? api.post('/users', body) : api.put(`/users/${user.id}`, body)));
      m.close();
      toast(isNew ? `Cuenta "${saved.username}" creada (${saved.is_active ? 'activa' : 'inactiva'}).` : 'Usuario actualizado.');
      onSaved();
    } catch { /* mostrado por campo */ }
  });
}

function openPasswordReset(user) {
  const form = document.createElement('form');
  form.noValidate = true;
  render(form, html`<p class="small muted">Se cerrarán todas las sesiones activas de <b>${user.username}</b>.</p>
    <div class="field mt-4"><label for="pr-1">Nueva contraseña</label><input id="pr-1" name="password" type="password" class="input" autocomplete="new-password" maxlength="128"></div>
    <div class="field mt-3"><label for="pr-2">Confirmar contraseña</label><input id="pr-2" name="password_confirm" type="password" class="input" autocomplete="new-password" maxlength="128"></div>
    <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button><button type="submit" class="btn btn-gold">Actualizar</button></div>`);
  const m = openModal({ title: 'Restablecer contraseña', body: form, size: 'sm' });
  const schema = { password: [rules.password], password_confirm: [rules.sameAs('password')] };
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(form, schema)) return;
    try {
      const r = await submitWith(form, form.querySelector('[type=submit]'), () => api.post(`/users/${user.id}/password`, formValues(form)));
      m.close();
      toast(r.message);
    } catch { /* mostrado */ }
  });
}

export default async function usersView(root, { user: me }) {
  const state = { q: '', role: '', active: '' };
  render(root, html`<div class="page-head"><div><h2>Usuarios del sistema</h2><p>Crea, edita, activa o desactiva cuentas y cambia roles.</p></div>
      <button type="button" class="btn btn-gold" data-new><i class="fa-solid fa-user-plus" aria-hidden="true"></i> Nueva cuenta</button></div>
    <div class="panel"><form class="filters panel-pad" id="uf" style="border-bottom:1px solid var(--line)">
      <div class="field"><label for="uf-q">Buscar</label><input id="uf-q" name="q" type="search" class="input" maxlength="60" placeholder="Nombre, usuario o correo"></div>
      <div class="field"><label for="uf-r">Rol</label><select id="uf-r" name="role" class="select"><option value="">Todos</option>${ROLES.map(([v, l]) => html`<option value="${v}">${l}</option>`)}</select></div>
      <div class="field"><label for="uf-a">Estado</label><select id="uf-a" name="active" class="select"><option value="">Todos</option><option value="true">Activos</option><option value="false">Inactivos</option></select></div>
    </form><div id="ut"></div></div>`);
  const table = $('#ut', root);
  let rows = [];
  const load = async () => {
    render(table, loading());
    try {
      rows = await api.get('/users', state);
      render(table, rows.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Estado</th><th>Último acceso</th><th class="text-right">Acciones</th></tr></thead>
        <tbody>${rows.map((u) => html`<tr><td data-label="Usuario"><span class="bold">${u.username}</span>${u.is_protected ? html` <span class="badge badge-plain b-gold">Principal</span>` : ''}${u.email ? html`<br><span class="xs faint">${u.email}</span>` : ''}</td>
          <td data-label="Nombre">${u.full_name}</td><td data-label="Rol">${ROLE_LABEL[u.role]}</td>
          <td data-label="Estado">${u.is_active ? html`<span class="badge b-ok">Activo</span>` : html`<span class="badge b-danger">Inactivo</span>`}</td>
          <td data-label="Último acceso">${u.last_login_at ? fmtDateTime(u.last_login_at) : '—'}</td>
          <td data-label="" class="cell-actions">
            <button type="button" class="btn btn-dark btn-xs" data-edit="${u.id}"><i class="fa-solid fa-pen" aria-hidden="true"></i> Editar</button>
            <button type="button" class="btn btn-ghost btn-xs" data-pass="${u.id}" aria-label="Restablecer contraseña de ${u.username}"><i class="fa-solid fa-key"></i></button>
            ${u.is_protected || u.id === me.id ? '' : html`<button type="button" class="btn btn-xs ${u.is_active ? 'btn-danger' : 'btn-gold'}" data-toggle="${u.id}">${u.is_active ? 'Desactivar' : 'Activar'}</button>`}
          </td></tr>`)}</tbody></table></div>` : emptyState('fa-users-slash', 'No hay usuarios con esos filtros.'));
    } catch (err) { render(table, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.addEventListener('click', async (e) => {
    if (e.target.closest('[data-new]')) { openUserForm(null, me, load).catch(toastError); return; }
    const get = (a) => rows.find((u) => u.id === Number(e.target.closest(`[${a}]`).getAttribute(a)));
    if (e.target.closest('[data-edit]')) openUserForm(get('data-edit'), me, load).catch(toastError);
    else if (e.target.closest('[data-pass]')) openPasswordReset(get('data-pass'));
    else if (e.target.closest('[data-toggle]')) {
      const u = get('data-toggle');
      const ok = await confirmDialog({ title: u.is_active ? `¿Desactivar a ${u.username}?` : `¿Activar a ${u.username}?`,
        message: u.is_active ? 'No podrá iniciar sesión y se cerrarán sus sesiones activas. Su historial se conserva.' : 'Podrá volver a iniciar sesión.',
        confirmText: u.is_active ? 'Desactivar' : 'Activar', danger: u.is_active });
      if (!ok) return;
      try {
        const saved = await api.patch(`/users/${u.id}/status`, { is_active: !u.is_active });
        toast(saved.is_active ? 'Cuenta activada.' : 'Cuenta desactivada.');
        load();
      } catch (err) { toastError(err); }
    }
  });
  const f = $('#uf', root);
  const apply = () => { Object.assign(state, formValues(f)); load(); };
  f.addEventListener('change', apply);
  f.addEventListener('input', debounce((e) => { if (e.target.name === 'q') apply(); }, 350));
  f.addEventListener('submit', (e) => e.preventDefault());
  load();
}
