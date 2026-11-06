import { api, currentUser } from '../../api.js';
import { formValues, html, raw, render, submitWith, toast } from '../../ui.js';
import { attachPhoneNormalizer, attachStrengthMeter, liveValidate, rules, validateForm } from '../../validators.js';

export default async function profileView(root, { user }) {
  const isClient = user.role === 'CLIENTE';
  render(root, html`<div class="page-head"><div><h2>Mi perfil</h2><p>Actualiza tus datos y tu contraseña.</p></div></div>
    <div class="grid grid-2" style="align-items:start">
      <form class="panel panel-pad" id="pf" novalidate autocomplete="off"><h3 class="mb-4">Datos personales</h3>
        <div class="grid">
          <div class="field"><label for="p-user">Usuario</label><input id="p-user" class="input" value="${user.username}" disabled></div>
          <div class="field"><label for="p-name">Nombre completo <span class="req">*</span></label><input id="p-name" name="full_name" class="input" maxlength="60" value="${user.full_name}"></div>
          ${isClient ? html`<div class="field"><label for="p-phone">Teléfono <span class="req">*</span></label><input id="p-phone" name="phone" class="input" inputmode="tel" maxlength="15" value="${user.client?.phone || ''}"></div>` : ''}
          <div class="field"><label for="p-email">Correo ${isClient ? raw('<span class="req">*</span>') : ''}</label><input id="p-email" name="email" type="email" class="input" maxlength="120" value="${user.email || ''}"></div>
        </div>
        <div class="form-actions"><button type="submit" class="btn btn-gold">Guardar cambios</button></div></form>
      <form class="panel panel-pad" id="pw" novalidate><h3 class="mb-4">Cambiar contraseña</h3>
        <div class="grid">
          <div class="field"><label for="pw-cur">Contraseña actual <span class="req">*</span></label><input id="pw-cur" name="current_password" type="password" class="input" autocomplete="current-password" maxlength="128"></div>
          <div class="field"><label for="pw-new">Nueva contraseña <span class="req">*</span></label><input id="pw-new" name="new_password" type="password" class="input" autocomplete="new-password" maxlength="128">
            <div class="strength" id="pw-strength" data-score="0" aria-hidden="true"><span></span><span></span><span></span><span></span></div><p class="field-hint" id="pw-label"></p></div>
          <div class="field"><label for="pw-new2">Confirmar nueva contraseña <span class="req">*</span></label><input id="pw-new2" name="new_password_confirm" type="password" class="input" autocomplete="new-password" maxlength="128"></div>
        </div>
        <p class="xs faint mt-3">Por seguridad se cerrarán tus otras sesiones abiertas.</p>
        <div class="form-actions"><button type="submit" class="btn btn-gold">Actualizar contraseña</button></div></form>
    </div>`);
  const pf = root.querySelector('#pf');
  if (pf.elements.phone) attachPhoneNormalizer(pf.elements.phone);
  const schema = { full_name: [rules.personName], email: [isClient ? rules.email : rules.optionalEmail], ...(isClient ? { phone: [rules.phone] } : {}) };
  liveValidate(pf, schema);
  pf.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(pf, schema)) return;
    const v = formValues(pf);
    try {
      await submitWith(pf, pf.querySelector('[type=submit]'), () => api.put('/auth/me', { full_name: v.full_name, email: v.email.trim() || null, ...(isClient ? { phone: v.phone } : {}) }));
      await currentUser(true);
      toast('Perfil actualizado.');
    } catch { /* mostrado */ }
  });
  const pw = root.querySelector('#pw');
  attachStrengthMeter(pw.elements.new_password, root.querySelector('#pw-strength'), root.querySelector('#pw-label'));
  const pwSchema = { current_password: [rules.required('Ingresa tu contraseña actual.')], new_password: [rules.password], new_password_confirm: [rules.sameAs('new_password')] };
  liveValidate(pw, pwSchema);
  pw.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(pw, pwSchema)) return;
    try {
      const r = await submitWith(pw, pw.querySelector('[type=submit]'), () => api.post('/auth/change-password', formValues(pw)));
      pw.reset();
      toast(r.message);
    } catch { /* mostrado */ }
  });
}
