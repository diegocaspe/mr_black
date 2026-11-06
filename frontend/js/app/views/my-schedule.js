import { api } from '../../api.js';
import { emptyState, html, loading, render } from '../../ui.js';
import { openTimeOff, scheduleEditor } from './barbers.js';

export default async function myScheduleView(root, { user }) {
  if (!user.barber_id) {
    render(root, emptyState('fa-user-slash', 'Tu cuenta no está vinculada a un perfil de barbero.'));
    return;
  }
  render(root, loading());
  try {
    const sched = await api.get(`/barbers/${user.barber_id}/schedule`);
    render(root, html`<div class="page-head"><div><h2>Mi horario</h2><p>Tu horario semanal lo define la administración. Puedes bloquear horarios puntuales (permisos, vacaciones).</p></div>
        <button type="button" class="btn btn-gold" data-timeoff><i class="fa-solid fa-plane" aria-hidden="true"></i> Mis bloqueos</button></div>
      <section class="panel panel-pad">${sched.length ? scheduleEditor(sched, { readOnly: true }) : emptyState('fa-clock', 'Aún no tienes un horario asignado.')}</section>`);
    root.querySelector('[data-timeoff]').addEventListener('click', () => openTimeOff({ id: user.barber_id, full_name: user.full_name }));
  } catch (err) {
    render(root, emptyState('fa-triangle-exclamation', err.message));
  }
}
