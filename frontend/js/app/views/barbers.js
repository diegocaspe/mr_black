import { api } from '../../api.js';
import {
  $, avatarImg, confirmDialog, DEFAULT_AVATAR, emptyState, fmtDateTime, formValues, html, loading, openModal, raw, render,
  stars, submitWith, toast, toastError,
} from '../../ui.js';
import { liveValidate, rules, validateForm } from '../../validators.js';

export const DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
const hhmm = (t) => (t ? t.slice(0, 5) : '');

function openBarberForm(barber, services, onSaved) {
  const b = barber || { full_name: '', description: '', photo_url: '', rating: '5.0', is_available: true, is_active: true, services: [] };
  const selected = new Set(b.services.map((s) => s.id));
  const form = document.createElement('form');
  form.noValidate = true;
  form.autocomplete = 'off';
  render(form, html`<div class="form-grid">
    <div class="field full flex" style="flex-direction:row;gap:16px;align-items:center">
      <img id="bf-preview" class="avatar" style="width:72px;height:72px" src="${b.photo_url || DEFAULT_AVATAR}" alt="Vista previa de la foto" data-fallback="${DEFAULT_AVATAR}">
      <div class="field grow"><label for="bf-photo">URL de la foto</label>
        <input id="bf-photo" name="photo_url" class="input" type="url" maxlength="500" placeholder="https://…" value="${b.photo_url || ''}">
        <p class="field-hint">Opcional. Si no carga, se mostrará una imagen por defecto.</p></div></div>
    <div class="field full"><label for="bf-name">Nombre <span class="req">*</span></label>
      <input id="bf-name" name="full_name" class="input" maxlength="60" required value="${b.full_name}">
      <p class="field-hint">Solo letras, espacios y tildes (máx. 60).</p></div>
    <div class="field"><label for="bf-rating">Valoración (0.0 – 5.0) <span class="req">*</span></label>
      <input id="bf-rating" name="rating" class="input" inputmode="decimal" maxlength="3" required value="${Number(b.rating).toFixed(1)}">
      <p class="field-hint" id="bf-stars">${stars(b.rating)}</p></div>
    <div class="field" style="justify-content:center;gap:12px">
      <label class="switch"><input type="checkbox" name="is_available" ${b.is_available ? raw('checked') : ''}> <span>Disponible para reservas</span></label>
      <label class="switch"><input type="checkbox" name="is_active" ${b.is_active ? raw('checked') : ''}> <span>Activo (visible)</span></label></div>
    <div class="field full"><label for="bf-desc">Descripción</label><textarea id="bf-desc" name="description" class="textarea" rows="2" maxlength="500">${b.description || ''}</textarea></div>
    <fieldset class="full" style="border:0;padding:0;margin:0"><legend class="label mb-2">Servicios que realiza <span class="req">*</span></legend>
      ${services.length ? '' : html`<p class="field-hint">Aún no hay servicios registrados. Crea al menos uno en Catálogo → Servicios para poder asignarlo.</p>`}
      <div class="choice-grid">${services.map((s) => html`<label class="choice"><input type="checkbox" name="service_ids" data-multi value="${s.id}" ${selected.has(s.id) ? raw('checked') : ''}>
        <span class="choice-icon"><i class="fa-solid ${s.icon}" aria-hidden="true"></i></span><span><span class="bold">${s.name}</span>${s.is_active ? '' : html`<br><span class="xs faint">Servicio inactivo</span>`}</span></label>`)}</div>
      <div class="field"><input type="hidden" name="services_check"></div></fieldset>
  </div>
  <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
    <button type="submit" class="btn btn-gold"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> Guardar</button></div>`);
  const m = openModal({ title: barber ? 'Editar barbero' : 'Nuevo barbero', kicker: 'Barberos', body: form, size: 'lg' });
  const photo = form.elements.photo_url;
  photo.addEventListener('change', () => { $('#bf-preview', form).src = !rules.imageUrl(photo.value) && photo.value.trim() ? photo.value.trim() : DEFAULT_AVATAR; });
  form.elements.rating.addEventListener('input', () => {
    const r = form.elements.rating.value;
    if (!rules.rating(r)) render($('#bf-stars', form), stars(r));
  });
  const schema = { full_name: [rules.personName], rating: [rules.rating], photo_url: [rules.imageUrl], description: [rules.maxLen(500)] };
  liveValidate(form, schema);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    let ok = validateForm(form, schema);
    const v = formValues(form);
    v.service_ids = v.service_ids || [];
    if (!v.service_ids.length) {
      ok = false;
      const box = form.querySelector('fieldset');
      box.querySelector('.field-error')?.remove();
      box.insertAdjacentHTML('beforeend', `<p class="field-error" data-generated>${services.length ? 'Selecciona al menos un servicio.' : 'Primero crea un servicio en Catálogo → Servicios.'}</p>`);
    }
    if (!ok) return;
    const body = {
      full_name: v.full_name, description: v.description.trim() || null, photo_url: v.photo_url.trim() || null,
      rating: v.rating.trim(), is_available: v.is_available, is_active: v.is_active, service_ids: v.service_ids.map(Number),
    };
    try {
      const saved = await submitWith(form, form.querySelector('[type=submit]'),
        () => (barber ? api.put(`/barbers/${barber.id}`, body) : api.post('/barbers', body)));
      m.close();
      toast(`Barbero "${saved.full_name}" guardado.`);
      onSaved();
    } catch { /* mostrado */ }
  });
}

export function scheduleEditor(schedules, { readOnly = false } = {}) {
  const byDay = new Map(schedules.map((s) => [s.weekday, s]));
  return html`${DAYS.map((d, i) => {
    const s = byDay.get(i);
    const dis = readOnly ? raw('disabled') : '';
    return html`<div class="schedule-row" data-day="${i}">
      <label class="switch"><input type="checkbox" data-works ${s ? raw('checked') : ''} ${dis}> <span class="bold">${d}</span></label>
      <div class="field"><label class="xs muted" for="sc-${i}-s">Inicio</label><input id="sc-${i}-s" type="time" class="input" data-k="start_time" value="${hhmm(s?.start_time) || '09:00'}" ${dis}></div>
      <div class="field"><label class="xs muted" for="sc-${i}-e">Fin</label><input id="sc-${i}-e" type="time" class="input" data-k="end_time" value="${hhmm(s?.end_time) || '19:30'}" ${dis}></div>
      <div class="field"><label class="xs muted" for="sc-${i}-bs">Descanso desde</label><input id="sc-${i}-bs" type="time" class="input" data-k="break_start" value="${hhmm(s?.break_start)}" ${dis}></div>
      <div class="field"><label class="xs muted" for="sc-${i}-be">Descanso hasta</label><input id="sc-${i}-be" type="time" class="input" data-k="break_end" value="${hhmm(s?.break_end)}" ${dis}></div>
    </div>`;
  })}`;
}

async function openSchedule(barber) {
  const sched = await api.get(`/barbers/${barber.id}/schedule`);
  const form = document.createElement('form');
  form.noValidate = true;
  render(form, html`<p class="small muted mb-4">Los días sin marcar son no laborables. El descanso es opcional y debe quedar dentro del horario.</p>
    <div id="sched">${scheduleEditor(sched)}</div>
    <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button><button type="submit" class="btn btn-gold">Guardar horario</button></div>`);
  const m = openModal({ title: `Horario de ${barber.full_name}`, kicker: 'Barberos', body: form, size: 'lg' });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const days = [];
    let error = null;
    form.querySelectorAll('[data-day]').forEach((row) => {
      if (!row.querySelector('[data-works]').checked) return;
      const val = (k) => row.querySelector(`[data-k="${k}"]`).value || null;
      const d = { weekday: Number(row.dataset.day), start_time: val('start_time'), end_time: val('end_time'), break_start: val('break_start'), break_end: val('break_end') };
      if (!d.start_time || !d.end_time || d.end_time <= d.start_time) error = error || `${DAYS[d.weekday]}: la hora de fin debe ser posterior a la de inicio.`;
      if (!!d.break_start !== !!d.break_end) error = error || `${DAYS[d.weekday]}: indica inicio y fin del descanso.`;
      if (d.break_start && (d.break_start < d.start_time || d.break_end > d.end_time || d.break_end <= d.break_start)) error = error || `${DAYS[d.weekday]}: el descanso debe estar dentro del horario.`;
      days.push(d);
    });
    if (error) { toast(error, 'err'); return; }
    try {
      await submitWith(form, form.querySelector('[type=submit]'), () => api.put(`/barbers/${barber.id}/schedule`, { days }));
      m.close();
      toast('Horario guardado.');
    } catch { /* mostrado */ }
  });
}

/** Gestión de bloqueos (vacaciones, días no laborables puntuales). Usado por admin y por el propio barbero. */
export async function openTimeOff(barber) {
  const box = document.createElement('div');
  const m = openModal({ title: `Bloqueos de ${barber.full_name}`, kicker: 'Vacaciones y días no laborables', body: box, size: 'lg' });
  const draw = async () => {
    render(box, loading());
    try {
      const list = await api.get(`/barbers/${barber.id}/time-off`);
      render(box, html`<form id="to-form" class="form-grid" novalidate>
          <div class="field"><label for="to-start">Desde <span class="req">*</span></label><input id="to-start" name="start_at" type="datetime-local" class="input" required></div>
          <div class="field"><label for="to-end">Hasta <span class="req">*</span></label><input id="to-end" name="end_at" type="datetime-local" class="input" required></div>
          <div class="field full"><label for="to-reason">Motivo</label><input id="to-reason" name="reason" class="input" maxlength="200" placeholder="Vacaciones, capacitación, permiso…"></div>
          <div class="full flex" style="justify-content:flex-end"><button type="submit" class="btn btn-gold"><i class="fa-solid fa-ban" aria-hidden="true"></i> Bloquear horario</button></div>
        </form>
        <h4 class="mt-6 mb-2">Bloqueos vigentes</h4>
        ${list.length ? list.map((t) => html`<div class="list-row"><div><div class="bold small">${fmtDateTime(t.start_at)} → ${fmtDateTime(t.end_at)}</div>
          <div class="xs faint">${t.reason || 'Sin motivo'}</div></div><button type="button" class="btn btn-ghost btn-xs" data-del="${t.id}"><i class="fa-solid fa-trash" aria-hidden="true"></i> Quitar</button></div>`)
          : emptyState('fa-calendar-check', 'No hay bloqueos vigentes.')}`);
      const f = $('#to-form', box);
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const schema = { start_at: [rules.required('Indica el inicio.')], end_at: [rules.required('Indica el fin.'), (v, fm) => (v <= fm.elements.start_at.value ? 'El fin debe ser posterior al inicio.' : null)] };
        if (!validateForm(f, schema)) return;
        const v = formValues(f);
        try {
          await submitWith(f, f.querySelector('[type=submit]'), () => api.post(`/barbers/${barber.id}/time-off`, { start_at: v.start_at, end_at: v.end_at, reason: v.reason.trim() || null }));
          toast('Horario bloqueado.');
          draw();
        } catch { /* mostrado */ }
      });
    } catch (err) { render(box, emptyState('fa-triangle-exclamation', err.message)); }
  };
  box.addEventListener('click', async (e) => {
    const d = e.target.closest('[data-del]');
    if (!d) return;
    if (!(await confirmDialog({ title: '¿Quitar el bloqueo?', message: 'El horario volverá a estar disponible para reservas.', confirmText: 'Quitar' }))) return;
    try { await api.del(`/barbers/${barber.id}/time-off/${d.dataset.del}`); toast('Bloqueo eliminado.'); draw(); } catch (err) { toastError(err); }
  });
  draw();
  return m;
}

export default async function barbersView(root) {
  const services = await api.get('/services', { all: true });
  render(root, html`<div class="page-head"><div><h2>Barberos</h2><p>Perfil, servicios, valoración, disponibilidad y horarios del equipo.</p></div>
    <button type="button" class="btn btn-gold" data-new><i class="fa-solid fa-plus" aria-hidden="true"></i> Nuevo barbero</button></div><div id="bl"></div>`);
  const box = $('#bl', root);
  let rows = [];
  const load = async () => {
    render(box, loading());
    try {
      rows = await api.get('/barbers/admin');
      render(box, rows.length ? html`<div class="cards" style="grid-template-columns:repeat(auto-fill,minmax(310px,1fr))">${rows.map((b) => html`
        <article class="panel panel-pad" style="${b.is_active ? '' : 'opacity:.6'}">
          <div class="flex gap-4 items-start">${avatarImg(b.photo_url, b.full_name)}
            <div class="grow"><h3 style="font-size:1.05rem">${b.full_name}</h3><div class="mt-1">${stars(b.rating)}</div>
              <div class="flex gap-2 wrap mt-2"><span class="badge ${b.is_available ? 'b-ok' : 'b-warn'}">${b.is_available ? 'Disponible' : 'No disponible'}</span>
                ${b.is_active ? '' : html`<span class="badge b-danger">Dado de baja</span>`}
                ${b.username ? html`<span class="badge badge-plain b-muted"><i class="fa-solid fa-user" aria-hidden="true"></i> ${b.username}</span>` : html`<span class="badge badge-plain b-muted">Sin cuenta</span>`}</div></div></div>
          <div class="chips">${b.services.map((s) => html`<span class="chip">${s.name}</span>`)}</div>
          <div class="grid grid-3 mt-4" style="gap:8px">
            <button type="button" class="btn btn-dark btn-sm" data-edit="${b.id}"><i class="fa-solid fa-pen" aria-hidden="true"></i> Editar</button>
            <button type="button" class="btn btn-dark btn-sm" data-schedule="${b.id}"><i class="fa-solid fa-clock" aria-hidden="true"></i> Horario</button>
            <button type="button" class="btn btn-dark btn-sm" data-timeoff="${b.id}"><i class="fa-solid fa-plane" aria-hidden="true"></i> Bloqueos</button></div>
        </article>`)}</div>` : emptyState('fa-user-tie', 'No hay barberos registrados.'));
    } catch (err) { render(box, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.addEventListener('click', (e) => {
    const find = (attr) => rows.find((b) => b.id === Number(e.target.closest(`[${attr}]`).getAttribute(attr)));
    if (e.target.closest('[data-new]')) openBarberForm(null, services, load);
    else if (e.target.closest('[data-edit]')) openBarberForm(find('data-edit'), services, load);
    else if (e.target.closest('[data-schedule]')) openSchedule(find('data-schedule')).catch(toastError);
    else if (e.target.closest('[data-timeoff]')) openTimeOff(find('data-timeoff'));
  });
  load();
}
