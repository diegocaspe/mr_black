/** Sitio público: servicios, barberos, reserva y tienda — todo desde la API real. */
import { api, currentUser, logout } from './api.js';
import { mountBooking } from './components/booking.js';
import { addToCart, loadCart, onCartChange, openCart } from './components/cart.js';
import { openProductDetail } from './components/product-detail.js';
import { bookService, openServiceDetail } from './components/service-detail.js';
import { $, avatarImg, debounce, emptyState, html, loading, money, productCover, raw, render, stars, toast, toastError } from './ui.js';

$('#year').textContent = new Date().getFullYear();

/* ------------------------------------------------------------------ cabecera */
const menuToggle = $('#menu-toggle');
menuToggle.addEventListener('click', () => {
  const nav = $('#mobile-nav');
  const open = !nav.classList.contains('open');
  nav.classList.toggle('open', open);
  menuToggle.setAttribute('aria-expanded', String(open));
});
$('#mobile-nav').addEventListener('click', (e) => {
  if (e.target.closest('a')) { $('#mobile-nav').classList.remove('open'); menuToggle.setAttribute('aria-expanded', 'false'); }
});

async function renderAuth() {
  const user = await currentUser().catch(() => null);
  const box = $('#auth-actions');
  if (user) {
    render(box, html`<a href="/app.html" class="btn btn-dark btn-sm"><i class="fa-solid fa-gauge" aria-hidden="true"></i><span class="hide-sm">Mi panel</span></a>
      <button type="button" class="btn btn-gold btn-sm" id="logout-btn" aria-label="Cerrar sesión"><i class="fa-solid fa-right-from-bracket" aria-hidden="true"></i></button>`);
    $('#logout-btn').addEventListener('click', async () => {
      await logout().catch(() => {});
      toast('Sesión cerrada.');
      setTimeout(() => location.reload(), 400);
    });
  } else {
    render(box, html`<a href="/login.html?next=${encodeURIComponent('/index.html')}" class="btn btn-dark btn-sm">Ingresar</a>
      <a href="/registro.html" class="btn btn-gold btn-sm">Registrarme</a>`);
  }
  $('#cart-btn').hidden = !(user && user.role === 'CLIENTE');
  if (user?.role === 'CLIENTE') loadCart().catch(() => {});
}

onCartChange((cart) => {
  const n = cart?.item_count || 0;
  const badge = $('#cart-count');
  badge.textContent = n;
  badge.hidden = !n;
  $('#cart-btn').setAttribute('aria-label', `Abrir carrito (${n} productos)`);
});
$('#cart-btn').addEventListener('click', openCart);

/* ------------------------------------------------------------------ catálogo */
/** Fotografía decorativa según el icono del servicio (solo presentación; sin coincidencia, se muestra el icono). */
const SERVICE_PHOTO = {
  'fa-scissors': 'photo-1622286342621-4bd786c2447c',
  'fa-user-tie': 'photo-1517832606299-7ae9b720a186',
  'fa-star': 'photo-1599351431202-1e0f0137899a',
  'fa-eye': 'photo-1596728325488-58c87691e9af',
};
const photoUrl = (id, w = 640) => `https://images.unsplash.com/${id}?w=${w}&q=65&auto=format&fit=crop`;

async function renderCatalog() {
  render($('#services'), loading());
  render($('#barbers'), loading());
  try {
    const [services, barbers, settings] = await Promise.all([api.get('/services'), api.get('/barbers'), api.get('/settings/public')]);
    render($('#services'), services.length ? html`${services.map((s, i) => {
      const decorative = SERVICE_PHOTO[s.icon] ? photoUrl(SERVICE_PHOTO[s.icon]) : '';
      const cover = s.images?.[0]?.url || decorative;
      return html`<article class="service-card" data-tilt>
        <button type="button" class="card-hit" data-open-service="${s.id}" data-fallback-photo="${decorative}" aria-label="Ver detalles de ${s.name}"></button>
        <div class="service-media ${cover ? '' : 'no-photo'}">
          ${cover ? html`<img src="${cover}" alt="" loading="lazy" decoding="async">` : ''}
          ${s.offer ? html`<span class="service-offer"><i class="fa-solid fa-tag" aria-hidden="true"></i> Oferta</span>` : ''}
          <span class="product-view" aria-hidden="true"><i class="fa-solid fa-eye"></i> Ver detalles</span>
          <span class="service-icon"><i class="fa-solid ${s.icon}" aria-hidden="true"></i></span>
          <span class="service-index" aria-hidden="true">${String(i + 1).padStart(2, '0')}</span>
        </div>
        <div class="service-body">
          <h3>${s.name}</h3>
          <p>${s.description || ''}</p>
          <div class="service-meta">
            <span class="price">${money(s.price)}</span>
            <span class="duration"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${s.duration_minutes} min</span>
          </div>
          <a href="#agendar" class="service-cta" data-book-service="${s.id}" aria-label="Reservar ${s.name}">Reservar <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></a>
        </div>
      </article>`;
    })}` : emptyState('fa-scissors', 'Pronto publicaremos nuestros servicios.'));

    render($('#barbers'), barbers.length ? html`${barbers.map((b) => html`
      <article class="barber-card ${b.is_available ? '' : 'is-off'}" data-tilt>
        <div class="barber-photo-wrap">
          ${avatarImg(b.photo_url, b.full_name, 'barber-photo')}
          <span class="badge ${b.is_available ? 'b-ok' : 'b-danger'}">${b.is_available ? 'Disponible' : 'No disponible'}</span>
        </div>
        <div class="barber-body">
          <h3>${b.full_name}</h3>
          <div class="barber-rating">${stars(b.rating)}</div>
          ${b.description ? html`<p class="barber-desc">${b.description}</p>` : ''}
          <div class="chips">${b.services.map((s) => html`<span class="chip">${s.name}</span>`)}</div>
        </div>
      </article>`)}` : emptyState('fa-user-tie', 'Pronto presentaremos a nuestro equipo.'));

    const b = settings.business;
    $('#footer-address').textContent = b.address;
    render($('#footer-contact'), html`<i class="fa-solid fa-phone" aria-hidden="true"></i> ${b.phone} · <i class="fa-regular fa-envelope" aria-hidden="true"></i> ${b.email}`);
  } catch (err) {
    render($('#services'), emptyState('fa-triangle-exclamation', err.message));
    render($('#barbers'), '');
  }
}

// Ficha del servicio (clic en la tarjeta) y "Reservar" con el servicio preseleccionado.
$('#services').addEventListener('click', (e) => {
  const book = e.target.closest('[data-book-service]');
  if (book) { e.preventDefault(); bookService(Number(book.dataset.bookService)); return; }
  const hit = e.target.closest('[data-open-service]') || e.target.closest('.service-card')?.querySelector('[data-open-service]');
  if (hit) openServiceDetail(Number(hit.dataset.openService), { fallbackImage: hit.dataset.fallbackPhoto, onChange: renderCatalog });
});

/* ------------------------------------------------------------------ tienda */
let categoriesLoaded = false;
async function renderShop() {
  const grid = $('#products');
  render(grid, loading());
  try {
    if (!categoriesLoaded) {
      const cats = await api.get('/categories');
      $('#shop-cat').insertAdjacentHTML('beforeend', html`${cats.map((c) => html`<option value="${c.id}">${c.name}</option>`)}`.s);
      categoriesLoaded = true;
    }
    const products = await api.get('/products', { q: $('#shop-q').value.trim(), category_id: $('#shop-cat').value });
    render(grid, products.length ? html`${products.map((p) => {
      const out = p.stock <= 0;
      const low = !out && p.stock_status === 'BAJO';
      return html`<article class="product-card ${out ? 'is-out' : ''}" data-tilt>
        <button type="button" class="product-hit" data-open="${p.id}" aria-label="Ver detalles de ${p.name}"></button>
        <div class="product-media"><span class="product-view" aria-hidden="true"><i class="fa-solid fa-eye"></i> Ver detalles</span>${productCover(p) ? html`<img src="${productCover(p)}" alt="${p.name}" loading="lazy">` : html`<i class="fa-solid ${p.icon}" aria-hidden="true"></i>`}
          <span class="product-cat">${p.category.name}</span></div>
        <div class="product-body">
          <div class="product-title"><h3>${p.name}</h3><span class="price nowrap">${money(p.price)}</span></div>
          <p class="desc">${p.description || ''}</p>
          <div class="product-foot">
            <span class="stock-note ${out ? 'out' : low ? 'low' : ''}">${out ? 'Agotado' : low ? `¡Últimas ${p.stock} unidades!` : `Stock: ${p.stock}`}</span>
            <button type="button" class="btn btn-gold btn-sm" data-add="${p.id}" ${out ? raw('disabled aria-disabled="true"') : ''}
              aria-label="Añadir ${p.name} al carrito"><i class="fa-solid fa-cart-plus" aria-hidden="true"></i> ${out ? 'Agotado' : 'Añadir'}</button>
          </div>
        </div>
      </article>`;
    })}` : emptyState('fa-box-open', 'No hay productos disponibles con esos filtros.'));
  } catch (err) {
    render(grid, emptyState('fa-triangle-exclamation', err.message));
  }
}
$('#products').addEventListener('click', async (e) => {
  const open = e.target.closest('[data-open]') || (!e.target.closest('[data-add]') && e.target.closest('.product-card')?.querySelector('[data-open]'));
  if (open) { openProductDetail(Number(open.dataset.open), { onChange: renderShop }); return; }
  const btn = e.target.closest('[data-add]');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  await addToCart(Number(btn.dataset.add));
  btn.disabled = false;
  renderShop();
});
$('#shop-q').addEventListener('input', debounce(renderShop, 350));
$('#shop-cat').addEventListener('change', renderShop);

/* ------------------------------------------------------------------ inicio */
renderAuth().catch(toastError);
renderCatalog();
renderShop();
mountBooking($('#booking'), { onDone: () => {} });
