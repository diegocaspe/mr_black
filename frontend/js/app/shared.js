/** Componentes compartidos entre vistas del panel. */
import { api } from '../api.js';
import { mountBooking } from '../components/booking.js';
import { mountPaymentSelector, paymentPayload, paymentSchema } from '../components/cart.js';
import {
  confirmDialog, emptyState, fmtDateTime, fmtLongDate, fmtTime, formValues, html, loading, money, openModal, raw,
  render, statusBadge, submitWith, toast, toastError,
} from '../ui.js';
import { validateForm } from '../validators.js';

export const ACTION_LABEL = {
  CONFIRMADA: { text: 'Confirmar', icon: 'fa-check', cls: 'btn-gold' },
  ATENDIDA: { text: 'Marcar atendida', icon: 'fa-user-check', cls: 'btn-outline-gold' },
  CANCELADA: { text: 'Cancelar', icon: 'fa-xmark', cls: 'btn-dark' },
};

/** Botones de transición permitidos (calculados por el backend según estado, rol y hora). */
export function appointmentActions(a, { compact = true } = {}) {
  const size = compact ? 'btn-xs' : 'btn-sm';
  return html`${a.allowed_transitions.map((s) => html`<button type="button" class="btn ${size} ${ACTION_LABEL[s].cls}" data-transition="${s}" data-id="${a.id}">
      <i class="fa-solid ${ACTION_LABEL[s].icon}" aria-hidden="true"></i> ${ACTION_LABEL[s].text}</button>`)}
    ${a.can_reschedule ? html`<button type="button" class="btn ${size} btn-dark" data-reschedule="${a.id}"><i class="fa-solid fa-calendar-days" aria-hidden="true"></i> Reprogramar</button>` : ''}
    ${a.can_charge ? html`<button type="button" class="btn ${size} btn-gold" data-charge="${a.id}"><i class="fa-solid fa-cash-register" aria-hidden="true"></i> Cobrar</button>` : ''}
    <button type="button" class="btn ${size} btn-ghost" data-detail="${a.id}" aria-label="Ver detalle de la cita"><i class="fa-solid fa-eye" aria-hidden="true"></i></button>`;
}

/** Conecta los botones de acciones de citas dentro de `root`; llama `refresh()` tras cada cambio. */
export function bindAppointmentActions(root, refresh) {
  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn || btn.disabled) return;
    if (btn.dataset.transition) {
      const to = btn.dataset.transition;
      const isCancel = to === 'CANCELADA';
      const res = await confirmDialog({
        title: isCancel ? '¿Cancelar la cita?' : to === 'CONFIRMADA' ? '¿Confirmar la cita?' : '¿Marcar como atendida?',
        message: isCancel ? 'La cita quedará cancelada (estado final) y el horario se liberará.'
          : to === 'ATENDIDA' ? 'La cita pasará a atendida (estado final). Luego podrás registrar el cobro.' : 'Se notificará al cliente por correo.',
        confirmText: isCancel ? 'Cancelar cita' : 'Confirmar',
        danger: isCancel,
        withReason: isCancel,
        reasonLabel: 'Motivo de la cancelación (opcional)',
      });
      if (!res) return;
      try {
        await api.patch(`/appointments/${btn.dataset.id}/status`, { status: to, note: res.reason || null });
        toast(isCancel ? 'Cita cancelada.' : 'Estado actualizado.');
        refresh();
      } catch (err) { toastError(err); refresh(); }
    } else if (btn.dataset.reschedule) {
      openReschedule(Number(btn.dataset.reschedule), refresh);
    } else if (btn.dataset.charge) {
      openCharge(Number(btn.dataset.charge), refresh);
    } else if (btn.dataset.detail) {
      openAppointmentDetail(Number(btn.dataset.detail), refresh);
    }
  });
}

export async function openReschedule(id, refresh) {
  try {
    const a = await api.get(`/appointments/${id}`);
    const box = document.createElement('div');
    const m = openModal({ title: 'Reprogramar cita', kicker: `${a.service.name} · ${a.client.full_name}`, body: box, size: 'lg' });
    mountBooking(box, { mode: 'reschedule', appointment: a, embedded: true, onDone: () => { m.close(); refresh(); } });
  } catch (err) { toastError(err); }
}

export async function openAppointmentDetail(id, refresh) {
  const box = document.createElement('div');
  render(box, loading());
  const m = openModal({ title: `Cita #${id}`, kicker: 'Detalle', body: box, size: 'lg' });
  try {
    const a = await api.get(`/appointments/${id}`);
    render(box, html`<div class="flex justify-between items-center wrap gap-2">${statusBadge(a.status)}
        ${a.sale_id ? html`<span class="badge b-ok">Cobrada</span>` : a.status === 'ATENDIDA' ? html`<span class="badge b-warn">Por cobrar</span>` : ''}</div>
      <dl class="detail-grid mt-4">
        <div class="detail"><dt>Cliente</dt><dd>${a.client.full_name} · ${a.client.phone}</dd></div>
        <div class="detail"><dt>Barbero</dt><dd>${a.barber.full_name}</dd></div>
        <div class="detail"><dt>Servicio</dt><dd>${a.service.name} (${a.service.duration_minutes} min)</dd></div>
        <div class="detail"><dt>Precio</dt><dd class="gold">${money(a.price)}</dd></div>
        <div class="detail"><dt>Fecha</dt><dd>${fmtLongDate(a.start_at)}</dd></div>
        <div class="detail"><dt>Horario</dt><dd>${fmtTime(a.start_at)} – ${fmtTime(a.end_at)}</dd></div>
      </dl>
      ${a.notes ? html`<p class="mt-4 small"><b>Comentario:</b> ${a.notes}</p>` : ''}
      ${a.cancel_reason ? html`<p class="mt-2 small"><b>Motivo de cancelación:</b> ${a.cancel_reason}</p>` : ''}
      <h3 class="mt-6 mb-2" style="font-size:1rem">Historial</h3>
      <ul class="timeline">${a.history.map((h) => html`<li><span class="bold small">${h.from_status ? `${h.from_status} → ${h.to_status}` : h.to_status}</span>
        <span class="xs faint"> · ${fmtDateTime(h.changed_at)}</span>${h.note ? html`<div class="small muted">${h.note}</div>` : ''}</li>`)}</ul>
      <div class="cell-actions mt-6" data-actions>${appointmentActions(a, { compact: false })}</div>`);
    box.querySelector('[data-detail]')?.remove();
    bindAppointmentActions(box, () => { m.close(); refresh?.(); });
  } catch (err) {
    render(box, emptyState('fa-triangle-exclamation', err.message));
  }
}

export async function openCharge(id, refresh) {
  try {
    const [a, methods] = await Promise.all([api.get(`/appointments/${id}`), api.get('/payments/methods')]);
    const form = document.createElement('form');
    form.noValidate = true;
    render(form, html`<div class="panel panel-pad" style="background:#191919">
        <div class="summary-row"><span>${a.service.name} · ${a.barber.full_name}</span><b>${money(a.price)}</b></div>
        <div class="summary-row"><span>Cliente</span><b>${a.client.full_name}</b></div>
        <div class="summary-row"><span class="bold" style="color:#fff">Total</span><b class="gold">${money(a.price)}</b></div></div>
      <div class="mt-5" data-pay-methods></div><div class="pay-panel" data-pay-fields></div>
      <div class="form-actions"><button type="button" class="btn btn-dark" data-close>Cancelar</button>
        <button type="submit" class="btn btn-gold"><i class="fa-solid fa-cash-register" aria-hidden="true"></i> Registrar cobro</button></div>`);
    const m = openModal({ title: 'Cobrar servicio', kicker: `Cita #${a.id}`, body: form, size: 'lg' });
    mountPaymentSelector(form, methods.filter((x) => x.counter_allowed));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const method = form.elements.payment_method.value;
      if (!validateForm(form, paymentSchema(method))) return;
      try {
        const sale = await submitWith(form, form.querySelector('[type=submit]'),
          () => api.post(`/appointments/${a.id}/charge`, { payment_method: method, payment: paymentPayload(formValues(form)) }));
        m.close();
        toast(`Cobro registrado. Comprobante ${sale.receipt_code}.`);
        openSaleDetail(sale.id, refresh, sale.change_due);
        refresh();
      } catch { /* mostrado en el formulario */ }
    });
  } catch (err) { toastError(err); }
}

/* ------------------------------------------------------------------ ventas */
export async function openSaleDetail(id, refresh, changeDue = null) {
  const box = document.createElement('div');
  render(box, loading());
  const m = openModal({ title: `Venta #${id}`, kicker: 'Detalle', body: box, size: 'lg' });
  try {
    const s = await api.get(`/sales/${id}`);
    render(box, html`<div class="flex justify-between items-center wrap gap-2">
        <div><span class="bold">${s.receipt_code}</span> <span class="xs faint">· ${fmtDateTime(s.created_at)}</span></div>${statusBadge(s.status)}</div>
      <dl class="detail-grid mt-4">
        <div class="detail"><dt>Cliente</dt><dd>${s.client ? `${s.client.full_name} · ${s.client.phone}` : 'Cliente varios'}</dd></div>
        <div class="detail"><dt>Canal</dt><dd>${s.channel === 'ONLINE' ? 'Tienda online' : 'Mostrador'}</dd></div>
        <div class="detail"><dt>Método</dt><dd>${s.payment_method_name}</dd></div>
        <div class="detail"><dt>Registrada por</dt><dd>${s.created_by_name || '—'}</dd></div>
        ${changeDue != null ? html`<div class="detail"><dt>Vuelto</dt><dd class="gold">${money(changeDue)}</dd></div>` : ''}
      </dl>
      <div class="table-wrap mt-4"><table class="table"><thead><tr><th>Descripción</th><th>Tipo</th><th class="text-right">Cant.</th><th class="text-right">P. unit.</th><th class="text-right">Importe</th></tr></thead>
        <tbody>${s.items.map((i) => html`<tr><td>${i.description}</td><td><span class="badge badge-plain b-muted">${i.item_type === 'SERVICIO' ? 'Servicio' : 'Producto'}</span></td>
          <td class="text-right">${i.quantity}</td><td class="text-right">${money(i.unit_price)}</td><td class="text-right">${money(i.line_total)}</td></tr>`)}</tbody></table></div>
      <div class="summary-row mt-2"><span class="bold" style="color:#fff">Total</span><b class="gold" style="font-size:1.15rem">${money(s.total)}</b></div>
      <h3 class="mt-6 mb-2" style="font-size:1rem">Pagos</h3>
      ${s.payments.map((p) => html`<div class="list-row"><div><div class="small bold">${p.payer_detail || p.method_code}</div>
        <div class="xs faint">${p.reference || 'Sin referencia'} · ${fmtDateTime(p.processed_at || p.created_at)}</div></div>
        <span class="badge ${p.status === 'APROBADO' ? 'b-ok' : p.status === 'PENDIENTE' ? 'b-warn' : 'b-danger'}">${p.status}</span></div>`)}
      ${s.cancel_reason ? html`<p class="small mt-4"><b>Motivo de anulación:</b> ${s.cancel_reason}</p>` : ''}`);
    const foot = document.createElement('div');
    foot.className = 'form-actions';
    render(foot, html`<a class="btn btn-dark" target="_blank" rel="noopener" href="${api.url(`/sales/${s.id}/receipt.pdf`)}"><i class="fa-solid fa-file-invoice" aria-hidden="true"></i> Ver PDF</a>
      <a class="btn btn-dark" href="${api.url(`/sales/${s.id}/receipt.pdf`, { download: true })}"><i class="fa-solid fa-download" aria-hidden="true"></i> Descargar</a>
      ${s.status === 'PENDIENTE_PAGO' ? html`<button type="button" class="btn btn-danger" data-cancel-sale>Anular pedido</button>` : ''}`);
    box.appendChild(foot);
    foot.querySelector('[data-cancel-sale]')?.addEventListener('click', async () => {
      const res = await confirmDialog({ title: '¿Anular el pedido?', message: 'El stock reservado se devolverá al inventario.', confirmText: 'Anular', danger: true, withReason: true });
      if (!res) return;
      try {
        await api.post(`/sales/${s.id}/cancel`, { reason: res.reason || null });
        toast('Pedido anulado y stock devuelto.');
        m.close();
        refresh?.();
      } catch (err) { toastError(err); }
    });
  } catch (err) {
    render(box, emptyState('fa-triangle-exclamation', err.message));
  }
}

/* ------------------------------------------------------------------ tablas */
export function pagination(page, pageSize, total) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return html`<div class="pagination"><span class="small muted">${total} resultado(s) · página ${page} de ${pages}</span>
    <div class="flex gap-2"><button type="button" class="btn btn-dark btn-sm" data-page="${page - 1}" ${page <= 1 ? raw('disabled') : ''}><i class="fa-solid fa-chevron-left" aria-hidden="true"></i> Anterior</button>
    <button type="button" class="btn btn-dark btn-sm" data-page="${page + 1}" ${page >= pages ? raw('disabled') : ''}>Siguiente <i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button></div></div>`;
}

/** Encabezado ordenable accesible (aria-sort). */
export function sortHeader(label, key, state) {
  const active = state.sort === key;
  const dir = active ? (state.order === 'asc' ? 'ascending' : 'descending') : null;
  const icon = !active ? 'fa-sort' : state.order === 'asc' ? 'fa-sort-up' : 'fa-sort-down';
  return html`<th ${dir ? raw(`aria-sort="${dir}"`) : ''}><button type="button" class="th-sort" data-sort="${key}" ${dir ? raw(`aria-sort="${dir}"`) : ''}>${label} <i class="fa-solid ${icon}" aria-hidden="true"></i></button></th>`;
}

export const options = (items, selected, valueKey = 'id', labelFn = (x) => x.full_name || x.name) =>
  html`${items.map((x) => html`<option value="${x[valueKey]}" ${String(x[valueKey]) === String(selected ?? '') ? raw('selected') : ''}>${labelFn(x)}</option>`)}`;
