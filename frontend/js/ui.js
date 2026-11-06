/** Utilidades de interfaz compartidas: plantillas seguras, formato, toasts, modales y formularios. */

export const TZ = 'America/Lima';

/* ------------------------------------------------------------------ plantillas seguras */
export class Raw {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}
export const raw = (s) => new Raw(String(s));

export function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function interp(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(interp).join('');
  if (v === false || v === null || v === undefined) return '';
  return esc(v);
}

/** Template tag: escapa todo valor interpolado salvo `raw(...)` o resultados de otro `html`. */
export function html(strings, ...values) {
  let out = '';
  strings.forEach((s, i) => { out += s + (i < values.length ? interp(values[i]) : ''); });
  return new Raw(out);
}

export function render(el, content) {
  el.innerHTML = content instanceof Raw ? content.s : esc(content);
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ------------------------------------------------------------------ formato */
const moneyFmt = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const money = (n) => `S/ ${moneyFmt.format(Number(n || 0))}`;

export function fmtDate(value, opts = { dateStyle: 'medium' }) {
  if (!value) return '—';
  const d = typeof value === 'string' && value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);
  return new Intl.DateTimeFormat('es-PE', { ...opts, timeZone: TZ }).format(d);
}
export const fmtDateTime = (v) => fmtDate(v, { dateStyle: 'medium', timeStyle: 'short' });
export const fmtTime = (v) => fmtDate(v, { hour: '2-digit', minute: '2-digit', hour12: false });
export const fmtLongDate = (v) => fmtDate(v, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

/** Fecha de hoy (YYYY-MM-DD) en la zona horaria de la barbería. */
export function todayISO(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  return parts;
}

export const STATUS_LABEL = {
  PENDIENTE: 'Pendiente', CONFIRMADA: 'Confirmada', ATENDIDA: 'Atendida', CANCELADA: 'Cancelada',
  PAGADA: 'Pagada', PENDIENTE_PAGO: 'Pago pendiente', ANULADA: 'Anulada',
};
export const statusBadge = (code) => html`<span class="badge st-${code}">${STATUS_LABEL[code] || code}</span>`;

/** 0024822: estrellas proporcionales al valor real (4.5 = 4 llenas + media; 4.2 = 4 llenas + 20 %). */
export function stars(rating, { label = true } = {}) {
  const r = Math.max(0, Math.min(5, Number(rating) || 0));
  const icons = (cls) => raw(Array.from({ length: 5 }, () => `<i class="${cls} fa-star" aria-hidden="true"></i>`).join(''));
  return html`<span class="stars" role="img" aria-label="Valoración ${r.toFixed(1)} de 5">
    <span class="stars-base">${icons('fa-regular')}</span>
    <span class="stars-fill" style="width:${(r / 5) * 100}%">${icons('fa-solid')}</span>
  </span>${label ? html`<span class="rating-label">${r.toFixed(1)}</span>` : ''}`;
}

/** Portada del producto: la foto por enlace o, si no hay, la primera foto subida. */
export const productCover = (p) => p.image_url || p.images?.[0]?.url || null;

export const DEFAULT_AVATAR = '/assets/avatar-default.svg';
export function avatarImg(url, alt, cls = 'avatar') {
  return html`<img class="${cls}" src="${url || DEFAULT_AVATAR}" alt="${alt}" loading="lazy" data-fallback="${DEFAULT_AVATAR}">`;
}
// Imagen por defecto si una URL falla (sin handlers inline por la CSP).
document.addEventListener('error', (e) => {
  const img = e.target;
  if (img instanceof HTMLImageElement && img.dataset.fallback && img.src !== new URL(img.dataset.fallback, location.href).href) {
    img.src = img.dataset.fallback;
  }
}, true);

export const debounce = (fn, ms = 300) => {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
};

/* ------------------------------------------------------------------ toasts */
export function toast(message, type = 'ok', ms = 4200) {
  let root = document.getElementById('toast-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'toast-root';
    root.className = 'toast-root';
    root.setAttribute('aria-live', 'polite');
    document.body.appendChild(root);
  }
  const icon = { ok: 'fa-circle-check', err: 'fa-circle-exclamation', info: 'fa-circle-info' }[type] || 'fa-circle-info';
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.setAttribute('role', type === 'err' ? 'alert' : 'status');
  render(el, html`<i class="fa-solid ${icon}" aria-hidden="true"></i><div>${message}</div>
    <button class="toast-close" type="button" aria-label="Cerrar aviso"><i class="fa-solid fa-xmark"></i></button>`);
  el.querySelector('.toast-close').addEventListener('click', () => el.remove());
  root.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

export function toastError(err) {
  toast(err?.message || 'Ocurrió un error inesperado.', 'err', 6000);
}

/* ------------------------------------------------------------------ modales (0022677) */
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const openModals = [];

/**
 * Abre un modal accesible. Solo se cierra con: botón X, botón Cancelar (data-close), tecla Escape,
 * o un clic cuyo mousedown Y mouseup ocurrieron sobre el overlay. Así, seleccionar texto dentro del
 * modal y soltar el mouse fuera ya no lo cierra.
 */
export function openModal({ title, body, footer = null, size = '', kicker = '', onClose = null, dismissible = true }) {
  const previous = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const id = `modal-${Math.random().toString(36).slice(2, 8)}`;
  render(overlay, html`<div class="modal ${size}" role="dialog" aria-modal="true" aria-labelledby="${id}-title">
    <div class="modal-head">
      <div>${kicker ? html`<div class="eyebrow">${kicker}</div>` : ''}<h2 class="modal-title" id="${id}-title">${title}</h2></div>
      <button type="button" class="icon-btn" data-close aria-label="Cerrar"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="modal-body"></div>
    ${footer ? html`<div class="modal-foot"></div>` : ''}
  </div>`);
  const bodyEl = overlay.querySelector('.modal-body');
  if (body instanceof Node) bodyEl.appendChild(body); else render(bodyEl, body ?? '');
  if (footer) {
    const footEl = overlay.querySelector('.modal-foot');
    if (footer instanceof Node) footEl.appendChild(footer); else render(footEl, footer);
  }

  let closed = false;
  const close = (result) => {
    if (closed) return;
    closed = true;
    overlay.remove();
    document.removeEventListener('keydown', onKey, true);
    openModals.splice(openModals.indexOf(api), 1);
    if (!openModals.length) document.body.classList.remove('modal-open');
    if (previous && previous.focus) previous.focus();
    onClose?.(result);
  };
  let downOnOverlay = false;
  overlay.addEventListener('mousedown', (e) => { downOnOverlay = e.target === overlay; });
  overlay.addEventListener('click', (e) => {
    const shouldClose = dismissible && downOnOverlay && e.target === overlay;
    downOnOverlay = false;
    if (shouldClose) close();
  });
  overlay.addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) { e.preventDefault(); close(); }
  });
  function onKey(e) {
    if (openModals[openModals.length - 1] !== api) return;
    if (e.key === 'Escape' && dismissible) { e.stopPropagation(); close(); }
    if (e.key === 'Tab') {
      const items = $$(FOCUSABLE, overlay).filter((n) => n.offsetParent !== null);
      if (!items.length) return;
      const first = items[0]; const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(overlay);
  document.body.classList.add('modal-open');
  const api = { el: overlay, body: bodyEl, close };
  openModals.push(api);
  const autofocus = overlay.querySelector('[autofocus]') || $$(FOCUSABLE, bodyEl)[0] || overlay.querySelector('[data-close]');
  setTimeout(() => autofocus?.focus(), 30);
  return api;
}

export function confirmDialog({ title = '¿Confirmar?', message = '', confirmText = 'Confirmar', danger = false, withReason = false, reasonLabel = 'Motivo (opcional)' }) {
  return new Promise((resolve) => {
    const body = html`<p class="muted">${message}</p>
      ${withReason ? html`<div class="field mt-4"><label for="confirm-reason">${reasonLabel}</label>
        <textarea id="confirm-reason" class="textarea" maxlength="300" rows="3"></textarea></div>` : ''}`;
    const footer = html`<button type="button" class="btn btn-dark" data-close>Cancelar</button>
      <button type="button" class="btn ${danger ? 'btn-danger' : 'btn-gold'}" data-ok>${confirmText}</button>`;
    let result = false;
    const m = openModal({ title, body, footer, size: 'sm', onClose: () => resolve(result) });
    m.el.querySelector('[data-ok]').addEventListener('click', () => {
      result = withReason ? { reason: m.el.querySelector('#confirm-reason').value.trim() } : true;
      m.close();
    });
  });
}

/* ------------------------------------------------------------------ formularios */
export function formValues(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === 'checkbox') {
      if (el.dataset.multi !== undefined) {
        out[el.name] = out[el.name] || [];
        if (el.checked) out[el.name].push(el.value);
      } else out[el.name] = el.checked;
    } else if (el.type === 'radio') {
      if (el.checked) out[el.name] = el.value;
    } else out[el.name] = el.value;
  }
  return out;
}

export function clearErrors(form) {
  $$('.field-error[data-generated]', form).forEach((n) => n.remove());
  $$('[aria-invalid="true"]', form).forEach((n) => n.removeAttribute('aria-invalid'));
  const alert = form.querySelector('.form-alert[data-generated]');
  if (alert) alert.remove();
}

export function setFieldError(form, name, message) {
  const input = form.querySelector(`[name="${CSS.escape(name)}"]`);
  const container = input ? (input.closest('.field') || input.parentElement) : null;
  if (!input || !container) return false;
  const existing = container.querySelector('.field-error[data-generated]');
  if (existing) existing.remove();
  const id = `${input.id || name}-error`;
  const p = document.createElement('p');
  p.className = 'field-error';
  p.id = id;
  p.dataset.generated = '';
  p.textContent = message;
  container.appendChild(p);
  if (input.type !== 'checkbox' && input.type !== 'radio') {
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-describedby', id);
  }
  return true;
}

export function clearFieldError(input) {
  const container = input.closest('.field') || input.parentElement;
  container?.querySelector('.field-error[data-generated]')?.remove();
  input.removeAttribute('aria-invalid');
}

/** Muestra errores por campo (del servidor o locales) y un aviso general si alguno no tiene campo. */
export function showErrors(form, fields = {}, message = null) {
  clearErrors(form);
  const orphan = [];
  Object.entries(fields).forEach(([name, msg]) => {
    const key = name.replace(/^payment\./, 'payment.');
    if (!setFieldError(form, key, msg) && !setFieldError(form, name.split('.').pop(), msg)) orphan.push(msg);
  });
  const generic = orphan.length ? orphan.join(' ') : (!Object.keys(fields).length ? message : null);
  if (generic) {
    const box = document.createElement('div');
    box.className = 'form-alert err';
    box.dataset.generated = '';
    box.setAttribute('role', 'alert');
    render(box, html`<i class="fa-solid fa-circle-exclamation" aria-hidden="true"></i><div>${generic}</div>`);
    form.prepend(box);
  }
  const firstInvalid = form.querySelector('[aria-invalid="true"]');
  firstInvalid?.focus();
}

/** Ejecuta `fn` mostrando estado de carga en el botón; mapea errores de la API a los campos. */
export async function submitWith(form, button, fn) {
  clearErrors(form);
  const label = button?.innerHTML;
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span> Procesando…';
  }
  try {
    return await fn();
  } catch (err) {
    if (err?.fields && Object.keys(err.fields).length) showErrors(form, err.fields, err.message);
    else showErrors(form, {}, err?.message || 'No se pudo completar la operación.');
    throw err;
  } finally {
    if (button) {
      button.disabled = false;
      button.innerHTML = label;
    }
  }
}

export const loading = (text = 'Cargando…') => html`<div class="loading"><span class="spinner" aria-hidden="true"></span>${text}</div>`;
export const emptyState = (icon, text) => html`<div class="empty"><i class="fa-solid ${icon}" aria-hidden="true"></i>${text}</div>`;
