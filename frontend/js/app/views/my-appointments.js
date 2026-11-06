import { api } from '../../api.js';
import { emptyState, fmtLongDate, fmtTime, html, loading, money, render, statusBadge } from '../../ui.js';
import { bindAppointmentActions } from '../shared.js';

const card = (a) => html`<article class="panel appt-card">
  <div><div class="gold xs bold" style="letter-spacing:.06em">${fmtLongDate(a.start_at).toUpperCase()} · ${fmtTime(a.start_at)}</div>
    <h3 class="mt-1" style="font-size:1.1rem">${a.service.name}</h3>
    <div class="small muted mt-1">${a.barber.full_name} · ${a.service.duration_minutes} min · ${money(a.price)}</div>
    ${a.cancel_reason ? html`<div class="xs faint mt-1">Motivo: ${a.cancel_reason}</div>` : ''}</div>
  <div class="flex items-start gap-2 wrap" style="justify-content:flex-end">${statusBadge(a.status)}
    <div class="cell-actions" style="width:100%">
      ${a.can_cancel ? html`<button type="button" class="btn btn-dark btn-sm" data-transition="CANCELADA" data-id="${a.id}"><i class="fa-solid fa-xmark" aria-hidden="true"></i> Cancelar</button>` : ''}
      ${a.can_reschedule ? html`<button type="button" class="btn btn-gold btn-sm" data-reschedule="${a.id}"><i class="fa-solid fa-calendar-days" aria-hidden="true"></i> Reprogramar</button>` : ''}
      <button type="button" class="btn btn-ghost btn-sm" data-detail="${a.id}">Detalle</button></div></div>
</article>`;

export default async function myAppointments(root) {
  render(root, html`<div class="page-head"><div><h2>Mis citas</h2><p>Consulta, cancela o reprograma tus reservas.</p></div>
    <a href="#/reservar" class="btn btn-gold"><i class="fa-solid fa-plus" aria-hidden="true"></i> Nueva cita</a></div>
    <h3 class="mb-4">Próximas</h3><div id="upcoming" class="grid"></div>
    <h3 class="mt-8 mb-4">Anteriores y canceladas</h3><div id="past" class="grid"></div>`);
  const up = root.querySelector('#upcoming');
  const past = root.querySelector('#past');
  const load = async () => {
    render(up, loading());
    try {
      const res = await api.get('/appointments', { sort: 'fecha', order: 'asc', page_size: 100 });
      const now = Date.now();
      const next = res.items.filter((a) => ['PENDIENTE', 'CONFIRMADA'].includes(a.status) && new Date(a.end_at).getTime() > now);
      const rest = res.items.filter((a) => !next.includes(a)).reverse();
      render(up, next.length ? html`${next.map(card)}` : emptyState('fa-calendar-plus', 'No tienes citas próximas. ¡Reserva la siguiente!'));
      render(past, rest.length ? html`${rest.slice(0, 20).map(card)}` : emptyState('fa-clock-rotate-left', 'Sin citas anteriores.'));
    } catch (err) { render(up, emptyState('fa-triangle-exclamation', err.message)); }
  };
  bindAppointmentActions(root, load);
  load();
}
