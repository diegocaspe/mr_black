/**
 * Asistente de reserva: Servicio → Barbero → Fecha y horario → Confirmación.
 * La disponibilidad se consulta al backend (horario, descansos, bloqueos, duración, citas
 * existentes y hora actual en la zona de la barbería). El servidor vuelve a validar al confirmar.
 */
import { api, currentUser } from '../api.js';
import {
  $, $$, avatarImg, emptyState, fmtLongDate, html, loading, money, raw, render, stars, todayISO, toast, toastError,
} from '../ui.js';

const STEPS = ['Servicio', 'Barbero', 'Fecha y hora', 'Confirmar'];
const REASON = { pasado: 'Hora pasada', ocupado: 'Ocupado', bloqueado: 'No disponible' };

export async function mountBooking(root, { mode = 'create', appointment = null, onDone = null, loginNext = '/index.html#agendar', embedded = false } = {}) {
  render(root, loading('Cargando servicios…'));
  let user = null;
  try { user = await currentUser(); } catch { /* sin sesión */ }

  if (mode === 'create' && (!user || user.role !== 'CLIENTE')) {
    renderLocked(root, user, loginNext);
    return;
  }

  let services = [];
  let barbers = [];
  let booking = { max_days_ahead: 60 };
  try {
    [services, barbers, { booking }] = await Promise.all([api.get('/services'), api.get('/barbers'), api.get('/settings/public')]);
  } catch (err) {
    render(root, emptyState('fa-triangle-exclamation', err.message));
    return;
  }

  const state = {
    step: mode === 'reschedule' ? 3 : 1,
    serviceId: appointment?.service.id ?? null,
    barberId: appointment?.barber.id ?? null,
    date: todayISO(),
    slot: null,
    availability: null,
    notes: '',
    busy: false,
  };
  if (appointment) {
    const d = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date(appointment.start_at));
    state.date = d >= todayISO() ? d : todayISO();
  }

  const service = () => services.find((s) => s.id === state.serviceId);
  const barber = () => barbers.find((b) => b.id === state.barberId);
  const eligible = () => barbers.filter((b) => b.services.some((s) => s.id === state.serviceId));

  async function loadSlots() {
    state.availability = null;
    state.slot = null;
    draw();
    try {
      state.availability = await api.get('/availability', {
        barber_id: state.barberId, service_id: state.serviceId, date: state.date,
        exclude_appointment_id: appointment?.id,
      });
    } catch (err) {
      state.availability = { working: false, message: err.message, slots: [] };
    }
    draw();
  }

  function stepper() {
    return html`<ol class="stepper" aria-label="Pasos de la reserva">${STEPS.map((s, i) => html`
      <li class="${state.step > i + 1 ? 'done' : state.step === i + 1 ? 'current' : ''}" ${state.step === i + 1 ? raw('aria-current="step"') : ''}>${i + 1}. ${s}</li>`)}</ol>`;
  }

  function back(label = 'Atrás') {
    if (mode === 'reschedule' && state.step <= 3) return '';
    return html`<button type="button" class="btn btn-ghost btn-sm" data-back><i class="fa-solid fa-arrow-left" aria-hidden="true"></i> ${label}</button>`;
  }

  function stepBody() {
    if (state.step === 1) {
      return html`<div class="flex justify-between items-center wrap gap-2"><h3>1. Elige tu servicio</h3></div>
        <div class="grid grid-2 mt-4">${services.map((s) => html`
          <button type="button" class="select-card" data-service="${s.id}" aria-pressed="${state.serviceId === s.id}">
            <div class="flex justify-between items-center"><i class="fa-solid ${s.icon} gold" style="font-size:1.25rem" aria-hidden="true"></i><span class="price">${money(s.price)}</span></div>
            <div class="bold mt-3">${s.name}</div>
            <div class="xs muted mt-1"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${s.duration_minutes} min${s.description ? ` · ${s.description}` : ''}</div>
          </button>`)}</div>`;
    }
    if (state.step === 2) {
      const list = eligible();
      return html`<div class="flex justify-between items-center wrap gap-2"><h3>2. Elige tu barbero</h3>${back()}</div>
        ${list.length ? html`<div class="grid grid-3 mt-4">${list.map((b) => html`
          <button type="button" class="select-card" data-barber="${b.id}" aria-pressed="${state.barberId === b.id}" ${b.is_available ? '' : raw('disabled')}>
            <div class="flex items-center gap-3">${avatarImg(b.photo_url, b.full_name, 'avatar avatar-sm')}
              <div class="grow"><div class="bold">${b.full_name}</div><div class="mt-1">${stars(b.rating)}</div></div></div>
            <div class="xs mt-3 ${b.is_available ? '' : 'faint'}" style="color:${b.is_available ? 'var(--ok)' : 'var(--danger)'}">
              ${b.is_available ? 'Disponible para reservar' : 'No disponible temporalmente'}</div>
          </button>`)}</div>` : emptyState('fa-user-slash', 'Ningún barbero ofrece este servicio por ahora.')}`;
    }
    if (state.step === 3) {
      const maxDate = todayISO(Number(booking.max_days_ahead || 60));
      const av = state.availability;
      let slotsHtml;
      if (!av) slotsHtml = loading('Consultando horarios…');
      else if (!av.working || !av.slots.length) slotsHtml = emptyState('fa-calendar-xmark', av.message || 'No hay horarios para esta fecha.');
      else {
        slotsHtml = html`<div class="slots" role="group" aria-label="Horarios">${av.slots.map((s) => html`
          <button type="button" class="slot" data-slot="${s.start_at}" aria-pressed="${state.slot === s.start_at}"
            ${s.available ? '' : raw('disabled')} title="${s.available ? 'Disponible' : REASON[s.reason] || 'No disponible'}"
            aria-label="${s.time}${s.available ? '' : ` (${REASON[s.reason] || 'no disponible'})`}">${s.time}</button>`)}</div>
          ${av.message ? html`<p class="small muted mt-3">${av.message}</p>` : ''}
          <p class="xs faint mt-3">Los horarios ocupados, bloqueados o que ya pasaron aparecen tachados.</p>`;
      }
      return html`<div class="flex justify-between items-center wrap gap-2"><h3>3. Fecha y horario</h3>${back()}</div>
        <div class="bk-when mt-4">
          <div class="field"><label for="bk-date">Fecha</label>
            <input id="bk-date" type="date" class="input" value="${state.date}" min="${todayISO()}" max="${maxDate}">
            ${mode === 'reschedule' ? html`<label for="bk-barber" class="mt-3">Barbero</label>
              <select id="bk-barber" class="select">${eligible().map((b) => html`<option value="${b.id}" ${b.id === state.barberId ? raw('selected') : ''} ${b.is_available ? '' : raw('disabled')}>${b.full_name}${b.is_available ? '' : ' (no disponible)'}</option>`)}</select>` : ''}
          </div>
          <div><div class="label mb-2">Horarios disponibles</div>${slotsHtml}</div>
        </div>
        <div class="form-actions"><button type="button" class="btn btn-gold" data-next ${state.slot ? '' : raw('disabled')}>Continuar <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div>`;
    }
    const s = service(); const b = barber();
    return html`<div class="flex justify-between items-center wrap gap-2"><h3>4. ${mode === 'reschedule' ? 'Confirma el nuevo horario' : 'Confirma tu reserva'}</h3>${back()}</div>
      <dl class="detail-grid mt-4">
        <div class="detail"><dt>Servicio</dt><dd>${s.name} · <span class="gold">${money(s.price)}</span></dd></div>
        <div class="detail"><dt>Barbero</dt><dd>${b.full_name}</dd></div>
        <div class="detail"><dt>Fecha</dt><dd>${fmtLongDate(state.slot)}</dd></div>
        <div class="detail"><dt>Hora</dt><dd>${new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(state.slot))} · ${s.duration_minutes} min</dd></div>
      </dl>
      ${mode === 'create' ? html`<div class="field mt-4"><label for="bk-notes">Comentario para el barbero (opcional)</label>
        <textarea id="bk-notes" class="textarea" maxlength="300" rows="2">${state.notes}</textarea></div>` : ''}
      <button type="button" class="btn btn-gold btn-block mt-6" data-confirm ${state.busy ? raw('disabled') : ''}>
        ${state.busy ? raw('<span class="spinner" aria-hidden="true"></span> Confirmando…') : raw('<i class="fa-solid fa-calendar-check" aria-hidden="true"></i> Confirmar')}
      </button>
      <p class="xs faint mt-3 center">${mode === 'create' ? 'Tu cita quedará pendiente hasta que la barbería la confirme. Recibirás un correo.' : 'Recibirás un correo con el nuevo horario.'}</p>`;
  }

  function summary() {
    const s = service(); const b = barber();
    return html`<aside class="panel panel-pad" aria-label="Resumen de la reserva">
      <div class="eyebrow">Tu reserva</div><h3 class="mt-2">Resumen</h3>
      <div class="mt-4">
        <div class="summary-row"><span>Servicio</span><b>${s ? s.name : '—'}</b></div>
        <div class="summary-row"><span>Duración</span><b>${s ? `${s.duration_minutes} min` : '—'}</b></div>
        <div class="summary-row"><span>Barbero</span><b>${b ? b.full_name : '—'}</b></div>
        <div class="summary-row"><span>Fecha</span><b>${state.step >= 3 ? fmtLongDate(state.slot || `${state.date}`) : '—'}</b></div>
        <div class="summary-row"><span>Hora</span><b>${state.slot ? new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(state.slot)) : '—'}</b></div>
        <div class="summary-row"><span>Total</span><b class="gold">${s ? money(s.price) : '—'}</b></div>
      </div>
      ${appointment ? html`<p class="xs faint mt-4">Horario actual: ${fmtLongDate(appointment.start_at)}</p>` : ''}
    </aside>`;
  }

  function draw() {
    render(root, html`<div class="${embedded ? 'grid' : 'booking'}">
      <div class="panel panel-pad">${mode === 'create' ? stepper() : ''}${stepBody()}</div>
      ${embedded ? '' : summary()}
    </div>`);
  }

  root.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t || !root.contains(t) || t.disabled) return;
    if (t.dataset.service) {
      state.serviceId = Number(t.dataset.service);
      state.barberId = null;
      state.slot = null;
      state.step = 2;
      draw();
    } else if (t.dataset.barber) {
      state.barberId = Number(t.dataset.barber);
      state.step = 3;
      loadSlots();
    } else if (t.dataset.slot) {
      state.slot = t.dataset.slot;
      $$('.slot', root).forEach((n) => n.setAttribute('aria-pressed', String(n === t)));
      const next = $('[data-next]', root);
      if (next) next.disabled = false;
      if (!embedded) draw();
      $('[data-next]', root)?.focus();
    } else if (t.hasAttribute('data-next')) {
      if (state.slot) { state.step = 4; draw(); }
    } else if (t.hasAttribute('data-back')) {
      state.step = Math.max(mode === 'reschedule' ? 3 : 1, state.step - 1);
      if (state.step === 3) loadSlots(); else draw();
    } else if (t.hasAttribute('data-confirm')) {
      await confirm();
    }
  });

  root.addEventListener('change', (e) => {
    if (e.target.id === 'bk-date') {
      const v = e.target.value;
      if (!v || v < todayISO()) {
        toast('No puedes reservar en una fecha pasada.', 'err');
        e.target.value = state.date;
        return;
      }
      state.date = v;
      loadSlots();
    } else if (e.target.id === 'bk-barber') {
      state.barberId = Number(e.target.value);
      loadSlots();
    }
  });
  root.addEventListener('input', (e) => { if (e.target.id === 'bk-notes') state.notes = e.target.value; });

  // "Reservar este servicio" desde la ficha del servicio: preselecciona el servicio y pasa al paso 2.
  if (mode === 'create') {
    const onPick = (e) => {
      if (!root.isConnected) { window.removeEventListener('mb:book-service', onPick); return; }
      const id = Number(e.detail?.serviceId);
      if (!services.some((s) => s.id === id)) return;
      Object.assign(state, { serviceId: id, barberId: null, slot: null, availability: null, step: 2 });
      draw();
    };
    window.addEventListener('mb:book-service', onPick);
  }

  async function confirm() {
    state.busy = true;
    draw();
    try {
      let result;
      if (mode === 'reschedule') {
        result = await api.post(`/appointments/${appointment.id}/reschedule`, { start_at: state.slot, barber_id: state.barberId });
        toast('Cita reprogramada correctamente.');
      } else {
        result = await api.post('/appointments', {
          service_id: state.serviceId, barber_id: state.barberId, start_at: state.slot, notes: state.notes || null,
        });
        toast('¡Cita registrada! Quedó pendiente de confirmación.');
      }
      state.busy = false;
      onDone?.(result);
      if (mode === 'create') {
        Object.assign(state, { step: 1, serviceId: null, barberId: null, slot: null, notes: '', availability: null });
        renderSuccess(result);
      }
    } catch (err) {
      state.busy = false;
      toastError(err);
      if (['slot_taken', 'slot_ocupado', 'slot_pasado', 'slot_bloqueado', 'slot_in_past'].includes(err.code)) {
        state.step = 3;
        loadSlots();
      } else draw();
    }
  }

  function renderSuccess(a) {
    render(root, html`<div class="panel panel-pad center" style="padding:48px 24px">
      <div class="lock-icon"><i class="fa-solid fa-check" aria-hidden="true"></i></div>
      <h3>¡Cita registrada!</h3>
      <p class="muted mt-2">${a.service.name} con ${a.barber.full_name} · ${fmtLongDate(a.start_at)}</p>
      <p class="xs faint mt-2">Estado: pendiente de confirmación. Te enviamos un correo con el detalle.</p>
      <div class="flex gap-2 wrap mt-6" style="justify-content:center">
        <a class="btn btn-gold" href="/app.html#/mis-citas"><i class="fa-solid fa-calendar-days" aria-hidden="true"></i> Ver mis citas</a>
        <button type="button" class="btn btn-dark" data-again>Reservar otra cita</button>
      </div></div>`);
    $('[data-again]', root)?.addEventListener('click', draw, { once: true });
  }

  if (state.step === 3) loadSlots(); else draw();
}

function renderLocked(root, user, loginNext) {
  const next = encodeURIComponent(loginNext);
  if (!user) {
    render(root, html`<div class="panel lock-box">
      <div class="lock-icon"><i class="fa-solid fa-lock" aria-hidden="true"></i></div>
      <h3>Inicia sesión para agendar</h3>
      <p class="muted mt-2">Regístrate como cliente o inicia sesión con tu cuenta.</p>
      <div class="flex gap-2 wrap mt-6" style="justify-content:center">
        <a class="btn btn-gold" href="/login.html?next=${next}">Ingresar</a>
        <a class="btn btn-dark" href="/registro.html?next=${next}">Crear cuenta</a>
      </div></div>`);
  } else {
    render(root, html`<div class="panel lock-box">
      <div class="lock-icon"><i class="fa-solid fa-user-tie" aria-hidden="true"></i></div>
      <h3>La agenda en línea está disponible para clientes</h3>
      <p class="muted mt-2">Si eres parte del equipo de Mr Black, registra las citas desde tu panel.</p>
      <a class="btn btn-gold mt-6" href="/app.html#/citas">Ir a mi panel</a></div>`);
  }
}
