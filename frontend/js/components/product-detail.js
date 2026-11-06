/**
 * Ficha de producto (tienda pública, tienda del cliente y panel del personal): galería de fotos,
 * precio, stock, cantidad y "Añadir al carrito".
 *
 * El personal (ADMIN y CAJA) gestiona las fotos desde la misma ficha: subir (se reducen en el
 * navegador), mover al inicio, eliminar y foto principal por enlace. Los clientes no ven estas
 * opciones y el backend rechaza cualquier intento (403).
 */
import { api, currentUser } from '../api.js';
import { addToCart, openCart } from './cart.js';
import { PHOTO_ROLES, bindPhotoInput, galleryView, photoManager, stepIndex, uploadPhotos } from './gallery.js';
import {
  confirmDialog, emptyState, formValues, html, loading, money, openModal, raw, render, submitWith, toast, toastError,
} from '../ui.js';
import { liveValidate, rules, validateForm } from '../validators.js';

/** Personal de la barbería: no compra desde la tienda en línea. */
const STAFF = ['ADMIN', 'CAJA', 'BARBERO'];

/**
 * @param {number} productId
 * @param {{ onChange?: Function, staffView?: boolean }} options
 *   staffView: abre desde el panel (lee /admin/products, así funciona aunque el producto esté dado de baja)
 *   y muestra el gestor de fotos desplegado.
 */
export async function openProductDetail(productId, { onChange = null, staffView = false } = {}) {
  const body = document.createElement('div');
  render(body, loading('Cargando producto…'));
  const modal = openModal({ title: 'Detalle del producto', kicker: staffView ? 'Fotos del producto' : 'Shop', body, size: 'lg' });
  const titleEl = modal.el.querySelector('.modal-title');

  let product;
  let user;
  const load = async () => {
    [product, user] = await Promise.all([
      api.get(staffView ? `/admin/products/${productId}` : `/products/${productId}`),
      currentUser().catch(() => null),
    ]);
  };
  try {
    await load();
  } catch (err) {
    render(body, emptyState('fa-triangle-exclamation', err.message));
    return;
  }

  const state = { qty: 1, active: 0, busy: false, added: false, uploading: '', managerOpen: staffView };
  const canManage = () => user && PHOTO_ROLES.includes(user.role);
  /** Galería: foto por enlace (si existe) y luego las fotos subidas, en su orden. */
  const gallery = () => [
    ...(product.image_url ? [{ src: product.image_url }] : []),
    ...(product.images || []).map((img) => ({ src: img.url })),
  ];
  const maxQty = () => Math.max(0, product.stock);

  function buyBox() {
    const out = product.stock <= 0;
    const low = !out && product.stock_status === 'BAJO';
    const stockText = out ? 'Agotado' : low ? `¡Últimas ${product.stock} unidades!` : `${product.stock} unidades disponibles`;
    const stock = html`<div class="pd-stock ${out ? 'out' : low ? 'low' : ''}"><i class="fa-solid fa-box" aria-hidden="true"></i> ${stockText}</div>`;
    if (user && STAFF.includes(user.role)) {
      return html`<div class="pd-buy">${stock}
        ${staffView ? '' : html`<div class="form-alert info mt-4"><i class="fa-solid fa-circle-info" aria-hidden="true"></i>
          <div>La tienda en línea está disponible para clientes. Registra la venta desde Caja.</div></div>`}
      </div>`;
    }
    return html`<div class="pd-buy">${stock}
      <div class="pd-qty-row">
        <span class="label" id="pd-qty-label">Cantidad</span>
        <div class="qty qty-lg" role="group" aria-labelledby="pd-qty-label">
          <button type="button" data-qty="-1" aria-label="Disminuir cantidad" ${out || state.qty <= 1 ? raw('disabled') : ''}><i class="fa-solid fa-minus" aria-hidden="true"></i></button>
          <output aria-live="polite">${out ? 0 : state.qty}</output>
          <button type="button" data-qty="1" aria-label="Aumentar cantidad" ${out || state.qty >= maxQty() ? raw('disabled') : ''}><i class="fa-solid fa-plus" aria-hidden="true"></i></button>
        </div>
      </div>
      ${!out && state.qty >= maxQty() ? html`<p class="xs mt-2" style="color:var(--warn)">Máximo disponible: ${maxQty()} unidades</p>` : ''}
      <div class="pd-total"><span>Total</span><b>${money(out ? 0 : Number(product.price) * state.qty)}</b></div>
      ${state.added ? html`<div class="pd-added" role="status"><i class="fa-solid fa-circle-check" aria-hidden="true"></i>
          <span>Añadido al carrito</span></div>
        <div class="pd-actions">
          <button type="button" class="btn btn-dark" data-close>Seguir comprando</button>
          <button type="button" class="btn btn-gold" data-go-cart><i class="fa-solid fa-bag-shopping" aria-hidden="true"></i> Ver carrito</button>
        </div>`
      : html`<button type="button" class="btn btn-gold btn-block pd-add" data-add-detail ${out || state.busy ? raw('disabled') : ''}>
          ${state.busy ? raw('<span class="spinner" aria-hidden="true"></span> Añadiendo…')
            : out ? 'Agotado' : raw('<i class="fa-solid fa-cart-plus" aria-hidden="true"></i> Añadir al carrito')}
        </button>`}
    </div>`;
  }

  function managerHtml() {
    if (!canManage()) return '';
    return html`<details class="pd-admin" ${state.managerOpen ? raw('open') : ''}>
      <summary><i class="fa-solid fa-camera" aria-hidden="true"></i> Gestionar fotos <span class="badge b-gold badge-plain">Solo personal</span></summary>
      <div class="pd-admin-body">
        ${photoManager({ uploads: product.images || [], coverIsUpload: !product.image_url, uploading: state.uploading })}
        <form class="pd-admin-form" novalidate>
          <div class="field"><label for="pd-img">Foto principal por enlace (opcional)</label>
            <input id="pd-img" name="image_url" class="input" type="url" maxlength="500" value="${product.image_url || ''}" placeholder="https://… o /assets/…">
            <p class="field-hint">Si hay un enlace, se muestra como portada antes de las fotos subidas.</p></div>
          <div class="form-actions">
            ${product.image_url ? html`<button type="button" class="btn btn-ghost btn-sm" data-remove-url><i class="fa-solid fa-link-slash" aria-hidden="true"></i> Quitar enlace</button>` : ''}
            <button type="submit" class="btn btn-gold btn-sm"><i class="fa-solid fa-floppy-disk" aria-hidden="true"></i> Guardar enlace</button>
          </div>
        </form>
      </div>
    </details>`;
  }

  function draw() {
    titleEl.textContent = product.name;
    const imgs = gallery();
    if (state.active >= imgs.length) state.active = 0;
    render(body, html`<div class="pd">
      ${galleryView({ images: imgs, active: state.active, alt: product.name, icon: product.icon, badge: product.category.name })}
      <div class="pd-info">
        <div class="pd-price">${money(product.price)}</div>
        ${staffView && product.is_active === false ? html`<span class="badge b-danger mt-2" style="align-self:flex-start">Dado de baja</span>` : ''}
        ${product.description ? html`<p class="pd-desc">${product.description}</p>` : html`<p class="pd-desc faint">Sin descripción.</p>`}
        ${buyBox()}
        ${managerHtml()}
      </div>
    </div>`);
    bindManager();
  }

  /** Aplica la respuesta del servidor (ProductOut con las fotos actualizadas). */
  function applyProduct(updated) {
    product = { ...product, ...updated };
    draw();
    onChange?.();
  }

  function bindManager() {
    const details = body.querySelector('.pd-admin');
    if (!details) return;
    details.addEventListener('toggle', () => { state.managerOpen = details.open; });
    bindPhotoInput(details, {
      busy: () => Boolean(state.uploading),
      onFiles: async (files) => {
        const { owner, done } = await uploadPhotos(files, {
          current: (product.images || []).length,
          url: `/admin/products/${product.id}/images`,
          onProgress: (text) => { state.uploading = text; draw(); },
        });
        state.uploading = '';
        state.managerOpen = true;
        if (owner) product = { ...product, ...owner };
        if (done) { state.active = gallery().length - 1; onChange?.(); }
        if (body.isConnected) draw();
      },
    });

    const form = body.querySelector('.pd-admin-form');
    const schema = { image_url: [rules.imageUrl] };
    liveValidate(form, schema);
    const saveUrl = async (url) => {
      const updated = await submitWith(form, form.querySelector('[type=submit]'),
        () => api.patch(`/admin/products/${product.id}/image`, { image_url: url }));
      state.active = 0;
      applyProduct(updated);
    };
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!validateForm(form, schema)) return;
      try {
        await saveUrl(formValues(form).image_url.trim() || null);
        toast('Enlace de la foto guardado.');
      } catch { /* errores mostrados en el formulario */ }
    });
    form.querySelector('[data-remove-url]')?.addEventListener('click', async () => {
      try {
        await saveUrl(null);
        toast('Enlace quitado.');
      } catch { /* errores mostrados en el formulario */ }
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
    } else if (t.dataset.qty) {
      state.qty = Math.min(maxQty(), Math.max(1, state.qty + Number(t.dataset.qty)));
      state.added = false;
      draw();
    } else if (t.dataset.first) {
      const id = Number(t.dataset.first);
      const ids = [id, ...product.images.map((i) => i.id).filter((x) => x !== id)];
      try {
        applyProduct(await api.put(`/admin/products/${product.id}/images/order`, { image_ids: ids }));
        toast('Foto movida al inicio.');
      } catch (err) { toastError(err); }
    } else if (t.dataset.delPhoto) {
      const ok = await confirmDialog({ title: '¿Eliminar esta foto?', message: 'Dejará de mostrarse en la tienda. Esta acción no se puede deshacer.', confirmText: 'Eliminar', danger: true });
      if (!ok) return;
      try {
        applyProduct(await api.del(`/admin/products/${product.id}/images/${t.dataset.delPhoto}`));
        toast('Foto eliminada.');
      } catch (err) { toastError(err); }
    } else if (t.hasAttribute('data-add-detail')) {
      state.busy = true;
      draw();
      const ok = await addToCart(product.id, state.qty);
      state.busy = false;
      if (ok) {
        state.added = true;
        onChange?.();
        try { await load(); } catch { /* se mantiene el último dato */ }
        state.qty = Math.min(state.qty, Math.max(1, maxQty()));
      }
      if (body.isConnected) {
        draw();
        body.querySelector(ok ? '[data-go-cart]' : '[data-add-detail]')?.focus();
      }
    } else if (t.hasAttribute('data-go-cart')) {
      modal.close();
      openCart();
    }
  });

  // Flechas del teclado para recorrer la galería (sin interferir con campos de texto).
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
