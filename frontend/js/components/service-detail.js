/**
 * Ficha de servicio: fotos de referencia, precio, duración, oferta, en qué consiste, qué incluye,
 * barberos que lo realizan y "Reservar este servicio" (preselecciona el servicio en la reserva).
 *
 * El personal (ADMIN y CAJA) edita la ficha y las fotos desde aquí. Precio, nombre y duración
 * se siguen editando solo en el panel de Servicios (ADMIN).
 */
import { api, currentUser } from '../api.js';
import { PHOTO_ROLES, bindPhotoInput, galleryView, photoManager, stepIndex, uploadPhotos } from './gallery.js';
import {
  avatarImg, confirmDialog, emptyState, formValues, html, loading, money, openModal, raw, render, submitWith, toast, toastError,
} from '../ui.js';
import { liveValidate, rules, validateForm } from '../validators.js';

export const BOOK_SERVICE_EVENT = 'mb:book-service';
const INCLUDES_MAX = 10;

/** Pide a la reserva de la página que preseleccione el servicio y lleva al usuario a ella. */
export function bookService(serviceId) {
  window.dispatchEvent(new CustomEvent(BOOK_SERVICE_EVENT, { detail: { serviceId } }));
  const target = document.getElementById('agendar');
  if (target) target.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  else location.href = '/index.html#agendar';
}

/**
 * @param {number} serviceId
 * @param {{ onChange?: Function, staffView?: boolean, fallbackImage?: string }} options
 *   staffView: abierto desde el panel (sin botón de reserva, editor desplegado).
 *   fallbackImage: foto decorativa si el servicio aún no tiene fotos propias.
 */
export async function openServiceDetail(serviceId, { onChange = null, staffView = false, fallbackImage = '' } = {}) {
  const body = document.createElement('div');
  render(body, loading('Cargando servicio…'));
  const modal = openModal({ title: 'Servicio', kicker: staffView ? 'Ficha del servicio' : 'Servicios', body, size: 'lg' });
  const titleEl = modal.el.querySelector('.modal-title');

  let service;
  let user;
  let barbers = [];
  try {
    [service, user, barbers] = await Promise.all([
      api.get(`/services/${serviceId}`),
      currentUser().catch(() => null),
      api.get('/barbers').catch(() => []),
    ]);
  } catch (err) {
    render(body, emptyState('fa-triangle-exclamation', err.message));
    return;
  }

  const state = { active: 0, uploading: '', managerOpen: staffView };
  const canManage = () => user && PHOTO_ROLES.includes(user.role);
  const gallery = () => {
    const own = (service.images || []).map((img) => ({ src: img.url }));
    return own.length ? own : fallbackImage ? [{ src: fallbackImage }] : [];
  };
  const doers = () => barbers.filter((b) => b.services.some((s) => s.id === service.id));

  function infoHtml() {
    const team = doers();
    return html`
      <div class="sd-head">
        <div class="pd-price">${money(service.price)}</div>
        <span class="sd-duration"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${service.duration_minutes} min</span>
      </div>
      ${staffView && !service.is_active ? html`<span class="badge b-danger mt-2" style="align-self:flex-start">Inactivo</span>` : ''}
      ${service.offer ? html`<div class="sd-offer"><i class="fa-solid fa-tag" aria-hidden="true"></i><div><span class="sd-offer-label">Oferta</span>${service.offer}</div></div>` : ''}
      <section class="sd-block" aria-labelledby="sd-what">
        <h3 id="sd-what" class="sd-title">En qué consiste</h3>
        <p class="pd-desc">${service.details || service.description || 'Pronto agregaremos más detalles de este servicio.'}</p>
      </section>
      ${service.includes?.length ? html`<section class="sd-block" aria-labelledby="sd-inc">
        <h3 id="sd-inc" class="sd-title">Qué incluye</h3>
        <ul class="sd-includes">${service.includes.map((item) => html`<li><i class="fa-solid fa-check" aria-hidden="true"></i>${item}</li>`)}</ul>
      </section>` : ''}
      ${team.length ? html`<section class="sd-block" aria-labelledby="sd-team">
        <h3 id="sd-team" class="sd-title">Lo realizan</h3>
        <ul class="sd-team">${team.map((b) => html`<li class="${b.is_available ? '' : 'is-off'}">
          ${avatarImg(b.photo_url, b.full_name, 'avatar avatar-sm')}<span>${b.full_name}${b.is_available ? '' : html`<small>No disponible</small>`}</span></li>`)}</ul>
      </section>` : ''}
      ${staffView ? '' : html`<button type="button" class="btn btn-gold btn-block pd-add mt-6" data-book>
        <i class="fa-solid fa-calendar-check" aria-hidden="true"></i> Reservar este servicio</button>`}`;
  }

  function managerHtml() {
    if (!canManage()) return '';
    return html`<details class="pd-admin" ${state.managerOpen ? raw('open') : ''}>
      <summary><i class="fa-solid fa-pen-to-square" aria-hidden="true"></i> Editar ficha y fotos <span class="badge b-gold badge-plain">Solo personal</span></summary>
      <div class="pd-admin-body">
        <form class="sd-form" novalidate>
          <div class="field"><label for="sd-details">En qué consiste</label>
            <textarea id="sd-details" name="details" class="textarea" rows="3" maxlength="1000" placeholder="Describe el servicio paso a paso…">${service.details || ''}</textarea></div>
          <div class="field mt-4"><label for="sd-includes">Qué incluye <span class="xs faint">(uno por línea, máx. ${INCLUDES_MAX})</span></label>
            <textarea id="sd-includes" name="includes" class="textarea" rows="4" placeholder="Lavado&#10;Toalla caliente&#10;Acabado con producto">${(service.includes || []).join('\n')}</textarea></div>
          <div class="field mt-4"><label for="sd-offer">Oferta o promoción (opcional)</label>
            <input id="sd-offer" name="offer" class="input" maxlength="120" value="${service.offer || ''}" placeholder="p. ej. 10 % de descuento los martes">
            <p class="field-hint">Se muestra como aviso en la tarjeta y en la ficha. No cambia el precio que se cobra.</p></div>
          <div class="form-actions"><button type="submit" class="btn btn-gold btn-sm"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> Guardar ficha</button></div>
        </form>
        <div class="pd-admin-form">
          <span class="label">Fotos de referencia</span>
          <div class="mt-2">${photoManager({ uploads: service.images || [], coverIsUpload: true, uploading: state.uploading })}</div>
        </div>
      </div>
    </details>`;
  }

  function draw() {
    titleEl.textContent = service.name;
    const imgs = gallery();
    if (state.active >= imgs.length) state.active = 0;
    render(body, html`<div class="pd">
      ${galleryView({ images: imgs, active: state.active, alt: service.name, icon: service.icon })}
      <div class="pd-info">${infoHtml()}${managerHtml()}</div>
    </div>`);
    bindManager();
  }

  function applyService(updated) {
    service = { ...service, ...updated };
    draw();
    onChange?.();
  }

  function bindManager() {
    const details = body.querySelector('.pd-admin');
    if (!details) return;
    details.addEventListener('toggle', () => { state.managerOpen = details.open; });

    const form = body.querySelector('.sd-form');
    const lines = (v) => String(v || '').split('\n').map((x) => x.trim()).filter(Boolean);
    const schema = {
      details: [rules.maxLen(1000)],
      includes: [(v) => {
        const items = lines(v);
        if (items.length > INCLUDES_MAX) return `Máximo ${INCLUDES_MAX} elementos.`;
        if (items.some((x) => x.length < 2 || x.length > 80)) return 'Cada elemento debe tener entre 2 y 80 caracteres.';
        return null;
      }],
      offer: [rules.maxLen(120)],
    };
    liveValidate(form, schema);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!validateForm(form, schema)) return;
      const v = formValues(form);
      const payload = { details: v.details.trim() || null, includes: lines(v.includes), offer: v.offer.trim() || null };
      try {
        const updated = await submitWith(form, form.querySelector('[type=submit]'),
          () => api.patch(`/services/${service.id}/content`, payload));
        state.managerOpen = true;
        applyService(updated);
        toast('Ficha del servicio guardada.');
      } catch { /* errores mostrados en el formulario */ }
    });

    bindPhotoInput(details, {
      busy: () => Boolean(state.uploading),
      onFiles: async (files) => {
        const { owner, done } = await uploadPhotos(files, {
          current: (service.images || []).length,
          url: `/services/${service.id}/images`,
          onProgress: (text) => { state.uploading = text; draw(); },
        });
        state.uploading = '';
        state.managerOpen = true;
        if (owner) service = { ...service, ...owner };
        if (done) { state.active = gallery().length - 1; onChange?.(); }
        if (body.isConnected) draw();
      },
    });
  }

  body.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t || t.disabled) return;
    if (t.dataset.thumb) {
      state.active = Number(t.dataset.thumb);
      draw();
      body.querySelector('.pd-thumb[aria-pressed="true"]')?.focus();
    } else if (t.dataset.step) {
      state.active = stepIndex(state.active, Number(t.dataset.step), gallery().length);
      draw();
      body.querySelector(`.pd-nav.${Number(t.dataset.step) > 0 ? 'next' : 'prev'}`)?.focus();
    } else if (t.dataset.first) {
      const id = Number(t.dataset.first);
      const ids = [id, ...service.images.map((i) => i.id).filter((x) => x !== id)];
      try {
        applyService(await api.put(`/services/${service.id}/images/order`, { image_ids: ids }));
        toast('Foto movida al inicio.');
      } catch (err) { toastError(err); }
    } else if (t.dataset.delPhoto) {
      const ok = await confirmDialog({ title: '¿Eliminar esta foto?', message: 'Dejará de mostrarse en la ficha del servicio. Esta acción no se puede deshacer.', confirmText: 'Eliminar', danger: true });
      if (!ok) return;
      try {
        applyService(await api.del(`/services/${service.id}/images/${t.dataset.delPhoto}`));
        toast('Foto eliminada.');
      } catch (err) { toastError(err); }
    } else if (t.hasAttribute('data-book')) {
      modal.close();
      bookService(service.id);
    }
  });

  body.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key) || e.target.closest('input, textarea, select')) return;
    const n = gallery().length;
    if (n < 2) return;
    state.active = stepIndex(state.active, e.key === 'ArrowRight' ? 1 : -1, n);
    draw();
    body.querySelector('.pd-thumb[aria-pressed="true"]')?.focus();
  });

  draw();
}
