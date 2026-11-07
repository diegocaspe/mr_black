import { api } from '../../api.js';
import { $, confirmDialog, emptyState, formValues, html, loading, render, submitWith, toast, toastError } from '../../ui.js';
import { attachPhoneNormalizer, liveValidate, rules, validateForm } from '../../validators.js';

export default async function settingsView(root, { query }) {
  render(root, loading());
  let s;
  let g;
  try {
    [s, g] = await Promise.all([api.get('/settings'), api.get('/integrations/google/status')]);
  } catch (err) {
    render(root, emptyState('fa-triangle-exclamation', err.message));
    return;
  }
  if (query.get('google') === 'ok') toast('Google Calendar conectado correctamente.');
  if (query.get('google') === 'error') toast('No se pudo conectar Google Calendar. Inténtalo nuevamente.', 'err');
  const b = s.business;
  const k = s.booking;
  render(root, html`<div class="page-head"><div><h2>Configuración</h2><p>Datos del negocio, reglas de agenda e integraciones.</p></div></div>
    <div class="grid grid-2" style="align-items:start">
      <form class="panel panel-pad" id="biz" novalidate><h3>Datos del negocio</h3><p class="small muted mt-1 mb-4">Aparecen en comprobantes, correos y en el sitio.</p>
        <div class="form-grid">
          <div class="field"><label for="b-name">Nombre comercial</label><input id="b-name" name="name" class="input" maxlength="60" value="${b.name}"></div>
          <div class="field"><label for="b-legal">Razón social</label><input id="b-legal" name="legal_name" class="input" maxlength="100" value="${b.legal_name}"></div>
          <div class="field"><label for="b-ruc">RUC</label><input id="b-ruc" name="ruc" class="input" inputmode="numeric" maxlength="11" value="${b.ruc}"></div>
          <div class="field"><label for="b-phone">Teléfono</label><input id="b-phone" name="phone" class="input" maxlength="15" value="${b.phone}"></div>
          <div class="field full"><label for="b-address">Dirección</label><input id="b-address" name="address" class="input" maxlength="150" value="${b.address}"></div>
          <div class="field full"><label for="b-email">Correo</label><input id="b-email" name="email" type="email" class="input" maxlength="120" value="${b.email}"></div>
        </div>
        <div class="form-actions"><button type="submit" class="btn btn-gold">Guardar</button></div></form>
      <form class="panel panel-pad" id="book" novalidate><h3>Reglas de agenda</h3><p class="small muted mt-1 mb-4">Se aplican al calcular la disponibilidad en el servidor.</p>
        <div class="form-grid">
          <div class="field"><label for="k-int">Intervalo entre horarios (min)</label><input id="k-int" name="slot_interval_minutes" type="number" class="input" min="5" max="120" value="${k.slot_interval_minutes}"></div>
          <div class="field"><label for="k-notice">Anticipación mínima (min)</label><input id="k-notice" name="min_notice_minutes" type="number" class="input" min="0" max="1440" value="${k.min_notice_minutes}"></div>
          <div class="field"><label for="k-days">Reservar hasta (días)</label><input id="k-days" name="max_days_ahead" type="number" class="input" min="1" max="365" value="${k.max_days_ahead}"></div>
          <div class="field"><label for="k-cancel">Cancelación del cliente (horas antes)</label><input id="k-cancel" name="client_cancel_min_hours" type="number" class="input" min="0" max="168" value="${k.client_cancel_min_hours}"></div>
          <div class="field"><label for="k-resched">Reprogramación (horas antes)</label><input id="k-resched" name="reschedule_min_hours" type="number" class="input" min="0" max="168" value="${k.reschedule_min_hours ?? 1}"><p class="field-hint">Aplica a clientes, caja y administrador.</p></div>
        </div>
        <div class="form-actions"><button type="submit" class="btn btn-gold">Guardar</button></div></form>
      <section class="panel panel-pad span-2"><div class="flex justify-between items-start wrap gap-4">
        <div><h3><i class="fa-brands fa-google gold" aria-hidden="true"></i> Google Calendar</h3>
          <p class="small muted mt-1">Al registrar, confirmar, reprogramar o cancelar una cita se crea, actualiza o elimina el evento en el calendario de la barbería.</p>
          <p class="mt-3">${!g.configured ? html`<span class="badge b-muted">No configurado</span> <span class="small muted">Define GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y GOOGLE_REDIRECT_URI en .env. El sistema funciona normalmente sin esta integración.</span>`
            : g.connected ? html`<span class="badge b-ok">Conectado</span> <span class="small muted">${g.account_email || ''} · calendario "${g.calendar_id}"</span>`
              : html`<span class="badge b-warn">Configurado, sin conectar</span>`}</p></div>
        <div class="flex gap-2">${g.configured ? (g.connected ? html`<button type="button" class="btn btn-danger" data-gdisconnect>Desconectar</button>`
          : html`<button type="button" class="btn btn-gold" data-gconnect><i class="fa-brands fa-google" aria-hidden="true"></i> Conectar cuenta</button>`) : ''}</div>
      </div></section>
    </div>`);

  const biz = $('#biz', root);
  attachPhoneNormalizer(biz.elements.phone);
  const bizSchema = {
    name: [(v) => (v.trim().length >= 3 ? null : 'Mínimo 3 caracteres.')],
    legal_name: [(v) => (v.trim().length >= 3 ? null : 'Mínimo 3 caracteres.')],
    ruc: [(v) => (/^(10|20)\d{9}$/.test(v.trim()) ? null : 'RUC inválido: 11 dígitos que empiezan con 10 o 20.')],
    phone: [rules.phone], address: [(v) => (v.trim().length >= 5 ? null : 'Mínimo 5 caracteres.')], email: [rules.email],
  };
  liveValidate(biz, bizSchema);
  biz.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(biz, bizSchema)) return;
    const v = formValues(biz);
    Object.keys(v).forEach((x) => { v[x] = v[x].trim(); });
    try { await submitWith(biz, biz.querySelector('[type=submit]'), () => api.put('/settings/business', v)); toast('Datos del negocio guardados.'); } catch { /* mostrado */ }
  });
  const book = $('#book', root);
  const bookSchema = {
    slot_interval_minutes: [rules.intRange(5, 120, 'El intervalo')], min_notice_minutes: [rules.intRange(0, 1440, 'La anticipación')],
    max_days_ahead: [rules.intRange(1, 365, 'El máximo de días')], client_cancel_min_hours: [rules.intRange(0, 168, 'El límite')],
    reschedule_min_hours: [rules.intRange(0, 168, 'El límite')],
  };
  book.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm(book, bookSchema)) return;
    const v = Object.fromEntries(Object.entries(formValues(book)).map(([x, y]) => [x, Number(y)]));
    try { await submitWith(book, book.querySelector('[type=submit]'), () => api.put('/settings/booking', v)); toast('Reglas de agenda guardadas.'); } catch { /* mostrado */ }
  });
  root.querySelector('[data-gconnect]')?.addEventListener('click', async () => {
    try { const r = await api.get('/integrations/google/connect'); location.href = r.authorization_url; } catch (err) { toastError(err); }
  });
  root.querySelector('[data-gdisconnect]')?.addEventListener('click', async () => {
    if (!(await confirmDialog({ title: '¿Desconectar Google Calendar?', message: 'Las nuevas citas dejarán de sincronizarse.', confirmText: 'Desconectar', danger: true }))) return;
    try { await api.del('/integrations/google'); toast('Google Calendar desconectado.'); settingsView(root, { query: new URLSearchParams() }); } catch (err) { toastError(err); }
  });
}
