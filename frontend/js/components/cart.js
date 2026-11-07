/**
 * Carrito persistido en el servidor + checkout con pago simulado.
 * - 0024820: el stock se valida en el servidor; los mensajes indican las unidades restantes y
 *   el botón "+" se limita al stock disponible.
 * - 0024817: un solo método de pago (radios con el mismo name) y opción "Pago en local".
 * - 0022634: el servidor rechaza totales de S/ 0.00; aquí además no se permite pagar si el total es 0.
 */
import { api, currentUser } from '../api.js';
import {
  $, emptyState, formValues, html, loading, money, openModal, raw, render, submitWith, toast, toastError,
} from '../ui.js';
import { attachPhoneNormalizer, liveValidate, rules, validateForm } from '../validators.js';

const listeners = new Set();
export const onCartChange = (fn) => listeners.add(fn);
const emit = (cart) => listeners.forEach((fn) => fn(cart));

let cache = null;

export async function loadCart() {
  const user = await currentUser().catch(() => null);
  if (!user || user.role !== 'CLIENTE') return null;
  cache = await api.get('/cart');
  emit(cache);
  return cache;
}

/**
 * Agrega al carrito con validación del servidor. Redirige al login si no hay sesión.
 * Devuelve true si el producto se añadió.
 */
export async function addToCart(productId, quantity = 1) {
  const user = await currentUser().catch(() => null);
  if (!user) {
    location.href = `/login.html?next=${encodeURIComponent('/index.html#tienda')}`;
    return false;
  }
  if (user.role !== 'CLIENTE') {
    toast('La tienda en línea está disponible para clientes. Registra la venta desde Caja.', 'info');
    return false;
  }
  try {
    cache = await api.post('/cart/items', { product_id: productId, quantity });
    emit(cache);
    toast(quantity > 1 ? `${quantity} unidades añadidas al carrito.` : 'Producto añadido al carrito.');
    return true;
  } catch (err) {
    toastError(err);
    return false;
  }
}

export async function openCart() {
  const user = await currentUser().catch(() => null);
  if (!user) {
    location.href = `/login.html?next=${encodeURIComponent('/index.html#tienda')}`;
    return;
  }
  if (user.role !== 'CLIENTE') {
    toast('El carrito está disponible para clientes.', 'info');
    return;
  }
  const overlay = document.createElement('div');
  overlay.className = 'drawer-overlay';
  const drawer = document.createElement('aside');
  drawer.className = 'drawer';
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-modal', 'true');
  drawer.setAttribute('aria-label', 'Carrito de compras');
  const previous = document.activeElement;
  const close = () => {
    overlay.remove();
    drawer.remove();
    document.removeEventListener('keydown', onKey);
    document.body.classList.remove('modal-open');
    previous?.focus?.();
  };
  const onKey = (e) => { if (e.key === 'Escape' && !document.querySelector('.modal-overlay')) close(); };
  overlay.addEventListener('click', close);
  document.addEventListener('keydown', onKey);
  document.body.append(overlay, drawer);
  document.body.classList.add('modal-open');

  const draw = (cart) => {
    const items = cart?.items || [];
    render(drawer, html`
      <div class="panel-head">
        <div><div class="eyebrow">Shop</div><h2 class="modal-title">Tu carrito</h2></div>
        <button type="button" class="icon-btn" data-close aria-label="Cerrar carrito"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="drawer-body">${!cart ? loading() : items.length ? items.map((it) => html`
        <div class="cart-line">
          <div class="thumb">${it.image_url ? html`<img src="${it.image_url}" alt="">` : html`<i class="fa-solid ${it.icon}" aria-hidden="true"></i>`}</div>
          <div class="grow">
            <div class="bold">${it.name}</div>
            <div class="small muted">${money(it.unit_price)} c/u</div>
            ${it.issue ? html`<div class="small mt-1" style="color:var(--danger)"><i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i> ${it.issue}</div>`
              : it.quantity >= it.stock ? html`<div class="xs mt-1" style="color:var(--warn)">Máximo disponible: ${it.stock} unidades</div>` : ''}
            <div class="flex items-center gap-2 mt-2">
              <div class="qty">
                <button type="button" data-dec="${it.product_id}" aria-label="Disminuir cantidad de ${it.name}" ${it.quantity <= 1 ? raw('disabled') : ''}><i class="fa-solid fa-minus"></i></button>
                <output aria-live="polite">${it.quantity}</output>
                <button type="button" data-inc="${it.product_id}" aria-label="Aumentar cantidad de ${it.name}" ${it.quantity >= it.stock || !it.available ? raw('disabled') : ''}><i class="fa-solid fa-plus"></i></button>
              </div>
              <button type="button" class="btn btn-ghost btn-xs" data-remove="${it.product_id}" aria-label="Quitar ${it.name}"><i class="fa-solid fa-trash"></i> Quitar</button>
            </div>
          </div>
          <div class="bold">${money(it.line_total)}</div>
        </div>`) : emptyState('fa-cart-shopping', 'Tu carrito está vacío.')}
      </div>
      ${items.length ? html`<div class="drawer-foot">
        ${cart.issues.length ? html`<div class="form-alert err mb-4" role="alert"><i class="fa-solid fa-circle-exclamation" aria-hidden="true"></i><div>Corrige los productos marcados antes de pagar.</div></div>` : ''}
        <div class="summary-row"><span>Subtotal</span><b>${money(cart.subtotal)}</b></div>
        <div class="summary-row"><span class="bold" style="color:#fff">Total</span><b class="gold" style="font-size:1.2rem">${money(cart.total)}</b></div>
        <div class="flex gap-2 mt-4">
          <button type="button" class="btn btn-dark" data-clear>Vaciar</button>
          <button type="button" class="btn btn-gold grow" data-checkout ${cart.can_checkout ? '' : raw('disabled')}>Continuar al pago <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button>
        </div></div>` : ''}`);
  };

  drawer.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t || t.disabled) return;
    try {
      if (t.hasAttribute('data-close')) return close();
      if (t.dataset.inc || t.dataset.dec) {
        const id = Number(t.dataset.inc || t.dataset.dec);
        const item = cache.items.find((i) => i.product_id === id);
        const qty = item.quantity + (t.dataset.inc ? 1 : -1);
        cache = await api.put(`/cart/items/${id}`, { quantity: qty });
      } else if (t.dataset.remove) {
        cache = await api.del(`/cart/items/${t.dataset.remove}`);
      } else if (t.hasAttribute('data-clear')) {
        cache = await api.del('/cart');
        toast('Carrito vaciado.');
      } else if (t.hasAttribute('data-checkout')) {
        openCheckout(cache, () => { close(); });
        return;
      }
      emit(cache);
      draw(cache);
    } catch (err) {
      toastError(err);
      cache = await api.get('/cart').catch(() => cache);
      emit(cache);
      draw(cache);
    }
  });

  draw(null);
  try {
    cache = await api.get('/cart');
    emit(cache);
    draw(cache);
    drawer.querySelector('[data-close]')?.focus();
  } catch (err) {
    toastError(err);
  }
}

/* ------------------------------------------------------------------ pago simulado */
export function paymentFields(method) {
  if (method === 'ONLINE') {
    return html`<div class="form-grid">
      <div class="field full"><label for="pay-card">Número de tarjeta</label>
        <input id="pay-card" name="payment.card_number" class="input" inputmode="numeric" autocomplete="cc-number" maxlength="19" placeholder="0000 0000 0000 0000"></div>
      <div class="field full"><label for="pay-holder">Titular</label>
        <input id="pay-holder" name="payment.card_holder" class="input" autocomplete="cc-name" maxlength="60"></div>
      <div class="field"><label for="pay-exp">Vencimiento (MM/AA)</label>
        <input id="pay-exp" name="payment.card_expiry" class="input" inputmode="numeric" autocomplete="cc-exp" maxlength="5" placeholder="MM/AA"></div>
      <div class="field"><label for="pay-cvv">CVV</label>
        <input id="pay-cvv" name="payment.card_cvv" class="input" inputmode="numeric" autocomplete="cc-csc" maxlength="3" type="password"></div>
      <p class="xs faint full"><i class="fa-solid fa-flask" aria-hidden="true"></i> Pago simulado: no se realiza ningún cobro real y no se guarda el número completo ni el CVV.</p>
    </div>`;
  }
  if (method === 'YAPE' || method === 'PLIN') {
    return html`<div class="form-grid">
      <div class="field"><label for="pay-phone">Celular ${method === 'YAPE' ? 'Yape' : 'Plin'}</label>
        <input id="pay-phone" name="payment.wallet_phone" class="input" inputmode="tel" maxlength="15" placeholder="9XXXXXXXX"></div>
      <div class="field"><label for="pay-code">Código de aprobación</label>
        <input id="pay-code" name="payment.approval_code" class="input" inputmode="numeric" maxlength="6" placeholder="6 dígitos"></div>
      <p class="xs faint full"><i class="fa-solid fa-flask" aria-hidden="true"></i> Simulación: el código 000000 se rechaza.</p>
    </div>`;
  }
  if (method === 'EFECTIVO') {
    return html`<div class="field"><label for="pay-received">Monto recibido (opcional, para calcular el vuelto)</label>
      <input id="pay-received" name="payment.amount_received" class="input" inputmode="decimal" maxlength="10" placeholder="0.00"></div>`;
  }
  if (method === 'LOCAL') {
    return html`<div class="form-alert info"><i class="fa-solid fa-store" aria-hidden="true"></i>
      <div>Reservamos tus productos y descontamos el stock. Pagas al recogerlos en la barbería con efectivo, Yape, Plin o tarjeta.</div></div>`;
  }
  return '';
}

function expiryError(v) {
  const m = /^(0[1-9]|1[0-2])\/(\d{2})$/.exec(v.trim());
  if (!m) return 'Usa el formato MM/AA (mes 01–12).';
  const now = new Date();
  const year = 2000 + Number(m[2]);
  const month = Number(m[1]);
  return year < now.getFullYear() || (year === now.getFullYear() && month < now.getMonth() + 1) ? 'La tarjeta está vencida.' : null;
}

/**
 * Formatea un campo mientras se escribe, pega o borra: deja solo dígitos (hasta `max`), los agrupa
 * con `format` y mantiene el cursor detrás del mismo número de dígitos.
 */
function maskDigits(input, max, format) {
  let prevDigits = input.value.replace(/\D/g, '');
  input.addEventListener('input', (e) => {
    const caret = input.selectionStart ?? input.value.length;
    let digitsBefore = input.value.slice(0, caret).replace(/\D/g, '').length;
    let digits = input.value.replace(/\D/g, '');
    // Retroceso sobre un separador (espacio o "/"): se borra el dígito anterior.
    if (e.inputType === 'deleteContentBackward' && digits === prevDigits && digitsBefore > 0) {
      digits = digits.slice(0, digitsBefore - 1) + digits.slice(digitsBefore);
      digitsBefore -= 1;
    }
    digits = digits.slice(0, max);
    prevDigits = digits;
    const formatted = format(digits);
    if (formatted === input.value) return;
    input.value = formatted;
    let pos = 0;
    for (let seen = 0; pos < formatted.length && seen < digitsBefore; pos += 1) {
      if (/\d/.test(formatted[pos])) seen += 1;
    }
    input.setSelectionRange(pos, pos);
  });
}

const groupsOf4 = (d) => d.replace(/(\d{4})(?=\d)/g, '$1 ');
// La "/" aparece al escribir el tercer dígito (MM/A…), así borrar nunca se queda trabado en ella.
const monthYear = (d) => (d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d);

function attachCardMasks(root) {
  const card = root.querySelector('[name="payment.card_number"]');
  const exp = root.querySelector('[name="payment.card_expiry"]');
  const cvv = root.querySelector('[name="payment.card_cvv"]');
  if (card) maskDigits(card, 16, groupsOf4);
  if (exp) maskDigits(exp, 4, monthYear);
  if (cvv) maskDigits(cvv, 3, (d) => d);
}

export function paymentSchema(method) {
  if (method === 'ONLINE') {
    return {
      'payment.card_number': [(v) => (/^\d{16}$/.test(v.replace(/\s/g, '')) ? null : 'El número de tarjeta debe tener 16 dígitos.')],
      'payment.card_holder': [rules.personName],
      'payment.card_expiry': [expiryError],
      'payment.card_cvv': [(v) => (/^\d{3}$/.test(v) ? null : 'El CVV debe tener 3 dígitos.')],
    };
  }
  if (method === 'YAPE' || method === 'PLIN') {
    return {
      'payment.wallet_phone': [rules.phone],
      'payment.approval_code': [(v) => (/^\d{6}$/.test(v) ? null : 'Ingresa el código de 6 dígitos.')],
    };
  }
  if (method === 'EFECTIVO') {
    return { 'payment.amount_received': [(v) => (!v || /^\d+(\.\d{1,2})?$/.test(v) ? null : 'Monto inválido.')] };
  }
  return {};
}

export function paymentPayload(values) {
  const p = {};
  Object.entries(values).forEach(([k, v]) => {
    if (k.startsWith('payment.') && String(v).trim() !== '') p[k.slice(8)] = String(v).trim();
  });
  if (p.card_number) p.card_number = p.card_number.replace(/[\s-]/g, '');
  return p;
}

/** Selector de método de pago (radio: un solo método a la vez) + campos del método elegido. */
export function mountPaymentSelector(form, methods, { name = 'payment_method' } = {}) {
  const box = form.querySelector('[data-pay-methods]');
  const fields = form.querySelector('[data-pay-fields]');
  render(box, html`<fieldset style="border:0;padding:0;margin:0"><legend class="label mb-2">Método de pago</legend>
    <div class="choice-grid">${methods.map((m, i) => html`
      <label class="choice"><input type="radio" name="${name}" value="${m.code}" ${i === 0 ? raw('checked') : ''} required>
        <span class="choice-icon"><i class="fa-solid ${ICONS[m.code] || 'fa-money-bill'}" aria-hidden="true"></i></span>
        <span><span class="bold">${m.name}</span><br><span class="xs muted">${m.description || ''}</span></span>
      </label>`)}</div></fieldset>`);
  const update = () => {
    const method = form.elements[name].value;
    render(fields, paymentFields(method));
    const phone = fields.querySelector('[name="payment.wallet_phone"]');
    if (phone) attachPhoneNormalizer(phone);
    attachCardMasks(fields);
    liveValidate(form, paymentSchema(method));
  };
  box.addEventListener('change', update);
  update();
}

export const ICONS = { ONLINE: 'fa-credit-card', YAPE: 'fa-mobile-screen', PLIN: 'fa-mobile-screen-button', EFECTIVO: 'fa-money-bill-wave', LOCAL: 'fa-store' };

async function openCheckout(cart, onPaid) {
  let methods = [];
  try {
    methods = (await api.get('/payments/methods')).filter((m) => m.online_allowed);
  } catch (err) {
    toastError(err);
    return;
  }
  if (Number(cart.total) <= 0) {
    toast('El total de la compra debe ser mayor a S/ 0.00.', 'err');
    return;
  }
  const form = document.createElement('form');
  form.noValidate = true;
  render(form, html`
    <div class="panel panel-pad" style="background:#191919">
      ${cart.items.map((i) => html`<div class="summary-row"><span>${i.name} × ${i.quantity}</span><b>${money(i.line_total)}</b></div>`)}
      <div class="summary-row"><span class="bold" style="color:#fff">Total a pagar</span><b class="gold" style="font-size:1.15rem">${money(cart.total)}</b></div>
    </div>
    <div class="mt-5" data-pay-methods></div>
    <div class="pay-panel" data-pay-fields></div>
    <div class="form-actions">
      <button type="button" class="btn btn-dark" data-close>Volver</button>
      <button type="submit" class="btn btn-gold"><i class="fa-solid fa-lock" aria-hidden="true"></i> Pagar ${money(cart.total)}</button>
    </div>`);
  const modal = openModal({ title: 'Método de pago', kicker: 'Checkout', body: form, size: 'lg' });
  mountPaymentSelector(form, methods);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const method = form.elements.payment_method.value;
    if (!validateForm(form, paymentSchema(method))) return;
    const values = formValues(form);
    try {
      const sale = await submitWith(form, form.querySelector('[type=submit]'),
        () => api.post('/cart/checkout', { payment_method: method, payment: paymentPayload(values) }));
      modal.close();
      onPaid?.(sale);
      cache = null;
      await loadCart();
      showSaleDone(sale);
    } catch (err) {
      if (err.code === 'insufficient_stock') {
        toastError(err);
        cache = await api.get('/cart').catch(() => cache);
        emit(cache);
      }
    }
  });
}

export function showSaleDone(sale) {
  const pending = sale.status === 'PENDIENTE_PAGO';
  const body = html`<div class="center">
    <div class="lock-icon"><i class="fa-solid ${pending ? 'fa-store' : 'fa-check'}" aria-hidden="true"></i></div>
    <h3>${pending ? 'Pedido reservado' : 'Pago aprobado'}</h3>
    <p class="muted mt-2">${pending ? 'Paga al recoger tus productos en la barbería.' : 'Tu compra fue registrada y el stock se actualizó.'}</p>
  </div>
  <div class="detail-grid mt-6">
    <div class="detail"><dt>Comprobante</dt><dd>${sale.receipt_code}</dd></div>
    <div class="detail"><dt>Total</dt><dd class="gold">${money(sale.total)}</dd></div>
    <div class="detail"><dt>Método</dt><dd>${sale.payment_method_name}</dd></div>
    <div class="detail"><dt>Estado</dt><dd>${pending ? 'Pago pendiente' : 'Pagado'}</dd></div>
    ${sale.change_due != null ? html`<div class="detail"><dt>Vuelto</dt><dd>${money(sale.change_due)}</dd></div>` : ''}
  </div>`;
  const footer = html`<a class="btn btn-dark" href="${api.url(`/sales/${sale.id}/receipt.pdf`, { download: true })}"><i class="fa-solid fa-download" aria-hidden="true"></i> Descargar PDF</a>
    <a class="btn btn-dark" target="_blank" rel="noopener" href="${api.url(`/sales/${sale.id}/receipt.pdf`)}"><i class="fa-solid fa-file-invoice" aria-hidden="true"></i> Ver comprobante</a>
    <button type="button" class="btn btn-gold" data-close>Listo</button>`;
  openModal({ title: '¡Gracias por tu compra!', body, footer });
}
