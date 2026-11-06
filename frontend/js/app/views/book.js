import { mountBooking } from '../../components/booking.js';
import { html, render } from '../../ui.js';

export default async function bookView(root) {
  render(root, html`<div class="page-head"><div><h2>Reservar cita</h2><p>Servicio → barbero → fecha y horario → confirmación.</p></div></div><div id="bk"></div>`);
  mountBooking(root.querySelector('#bk'), { loginNext: '/app.html#/reservar' });
}
