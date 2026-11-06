/**
 * Capa de experiencia del sitio público: estado de la cabecera, sección activa, menú móvil,
 * revelado progresivo, parallax ligero del hero e inclinación 3D sutil de las tarjetas.
 * Solo presentación: no lee ni modifica datos, ni sustituye la lógica de public.js.
 */
const doc = document.documentElement;
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
const hasIO = 'IntersectionObserver' in window;
const motionOK = () => !reduceMotion.matches;

if (hasIO) doc.classList.add('js-motion');

/* ------------------------------------------------------------------ cabecera */
const header = document.querySelector('.site-header');
const hero = document.getElementById('inicio');

if (header && hasIO) {
  const sentinel = document.createElement('div');
  sentinel.className = 'scroll-sentinel';
  sentinel.setAttribute('aria-hidden', 'true');
  document.body.prepend(sentinel);
  new IntersectionObserver(([entry]) => {
    header.classList.toggle('is-scrolled', !entry.isIntersecting);
  }).observe(sentinel);
} else header?.classList.add('is-scrolled');

/* ------------------------------------------------------------------ sección activa */
const navLinks = [...document.querySelectorAll('.site-nav a[href^="#"], .mobile-nav a[href^="#"]')];
const sections = [...new Set(navLinks.map((a) => a.getAttribute('href')))]
  .map((id) => document.querySelector(id)).filter(Boolean);

function setActive(id) {
  navLinks.forEach((a) => {
    if (a.getAttribute('href') === `#${id}`) a.setAttribute('aria-current', 'location');
    else a.removeAttribute('aria-current');
  });
}
if (hasIO && sections.length) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) setActive(e.target.id); });
  }, { rootMargin: '-45% 0px -50% 0px' });
  sections.forEach((s) => io.observe(s));
  if (hero) {
    new IntersectionObserver(([e]) => { if (e.isIntersecting) setActive(''); }, { rootMargin: '-45% 0px -50% 0px' }).observe(hero);
  }
}

/* ------------------------------------------------------------------ menú móvil
   public.js abre/cierra el menú con la clase .open; aquí solo se añade cierre con Escape
   o clic fuera, manteniendo el mismo contrato (clase + aria-expanded). */
const menuToggle = document.getElementById('menu-toggle');
const mobileNav = document.getElementById('mobile-nav');
function closeMenu({ focus = false } = {}) {
  if (!mobileNav?.classList.contains('open')) return;
  mobileNav.classList.remove('open');
  menuToggle.setAttribute('aria-expanded', 'false');
  if (focus) menuToggle.focus();
}
if (menuToggle && mobileNav) {
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu({ focus: true }); });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#mobile-nav, #menu-toggle')) closeMenu();
  });
  new MutationObserver(() => {
    menuToggle.setAttribute('aria-label', mobileNav.classList.contains('open') ? 'Cerrar menú' : 'Abrir menú');
  }).observe(mobileNav, { attributes: true, attributeFilter: ['class'] });
}

/* ------------------------------------------------------------------ revelado al hacer scroll */
if (hasIO) {
  const revealIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.classList.add('is-visible');
      revealIO.unobserve(e.target);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  document.querySelectorAll('[data-reveal]').forEach((el) => revealIO.observe(el));

  /* Rejillas que public.js rellena desde la API. Se revelan una sola vez, cuando ya tienen
     tarjetas y están en pantalla; los re-renderizados posteriores (filtros, "Añadir") aparecen
     al instante, sin repetir la animación. */
  const grids = [...document.querySelectorAll('.reveal-grid')];
  const tryReveal = (grid) => {
    if (grid.dataset.revealed || !grid.dataset.inview) return;
    const cards = [...grid.children].filter((c) => c.tagName === 'ARTICLE');
    if (!cards.length) return;
    cards.forEach((c, i) => c.style.setProperty('--i', String(Math.min(i, 8))));
    grid.dataset.revealed = '1';
    requestAnimationFrame(() => requestAnimationFrame(() => grid.classList.add('is-visible')));
  };
  const gridIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.dataset.inview = '1';
      tryReveal(e.target);
      gridIO.unobserve(e.target);
    });
  }, { threshold: 0.05 });
  grids.forEach((g) => {
    gridIO.observe(g);
    new MutationObserver(() => tryReveal(g)).observe(g, { childList: true });
  });
}

/* ------------------------------------------------------------------ hero: parallax y profundidad
   Un solo bucle rAF combina el scroll (el fondo baja más lento y el texto se desvanece) con la
   posición del puntero (el fondo se desplaza en sentido contrario y el bloque de texto se inclina
   unos grados, con sus capas a distinta profundidad). Solo corre mientras el hero está visible. */
const heroBg = document.querySelector('.hero-bg');
const heroInner = document.querySelector('.hero-inner');
const heroCopy = document.querySelector('.hero-copy');
if (hero && heroBg && hasIO) {
  let heroVisible = true;
  let ticking = false;
  const ptr = { x: 0, y: 0 };
  const update = () => {
    ticking = false;
    if (!heroVisible || !motionOK()) return;
    const y = Math.min(window.scrollY, hero.offsetHeight);
    heroBg.style.transform = `translate3d(${(-ptr.x * 22).toFixed(1)}px, ${(y * 0.24 - ptr.y * 14).toFixed(1)}px, 0) scale(1.1)`;
    if (heroInner) {
      heroInner.style.transform = `translate3d(0, ${(y * 0.12).toFixed(1)}px, 0)`;
      heroInner.style.opacity = String(Math.max(0, 1 - y / (hero.offsetHeight * 0.8)).toFixed(3));
    }
    if (heroCopy) {
      heroCopy.style.setProperty('--ry', `${(ptr.x * 5).toFixed(2)}deg`);
      heroCopy.style.setProperty('--rx', `${(-ptr.y * 3.5).toFixed(2)}deg`);
    }
  };
  const request = () => {
    if (!ticking && heroVisible) { ticking = true; requestAnimationFrame(update); }
  };
  new IntersectionObserver(([e]) => { heroVisible = e.isIntersecting; }).observe(hero);
  window.addEventListener('scroll', request, { passive: true });
  hero.addEventListener('pointermove', (e) => {
    if (!finePointer.matches || e.pointerType !== 'mouse') return;
    ptr.x = e.clientX / window.innerWidth - 0.5;
    ptr.y = e.clientY / window.innerHeight - 0.5;
    request();
  });
  hero.addEventListener('pointerleave', () => { ptr.x = 0; ptr.y = 0; request(); });
  reduceMotion.addEventListener?.('change', () => {
    if (!reduceMotion.matches) return;
    heroBg.style.transform = '';
    if (heroInner) { heroInner.style.transform = ''; heroInner.style.opacity = ''; }
    heroCopy?.style.removeProperty('--rx');
    heroCopy?.style.removeProperty('--ry');
  });
}

/* ------------------------------------------------------------------ 3D sutil */
const MAX_TILT = 6;

/** Inclina el elemento según la posición del puntero (variables CSS --rx/--ry/--mx/--my). */
function bindTilt(container, selector, max = MAX_TILT) {
  let frame = 0;
  let current = null;
  let point = null;
  const apply = () => {
    frame = 0;
    if (!current || !point) return;
    const r = current.getBoundingClientRect();
    const px = (point.x - r.left) / r.width;
    const py = (point.y - r.top) / r.height;
    current.style.setProperty('--ry', `${((px - 0.5) * 2 * max).toFixed(2)}deg`);
    current.style.setProperty('--rx', `${((0.5 - py) * 2 * max).toFixed(2)}deg`);
    current.style.setProperty('--mx', `${(px * 100).toFixed(1)}%`);
    current.style.setProperty('--my', `${(py * 100).toFixed(1)}%`);
  };
  const reset = (el) => {
    if (!el) return;
    el.classList.remove('is-tilting');
    ['--rx', '--ry', '--mx', '--my'].forEach((p) => el.style.removeProperty(p));
  };
  container.addEventListener('pointermove', (e) => {
    if (!finePointer.matches || !motionOK() || e.pointerType !== 'mouse') return;
    const el = selector ? e.target.closest(selector) : container;
    if (el !== current) { reset(current); current = el; }
    if (!el || (selector && !container.contains(el))) return;
    el.classList.add('is-tilting');
    point = { x: e.clientX, y: e.clientY };
    if (!frame) frame = requestAnimationFrame(apply);
  });
  container.addEventListener('pointerleave', () => { reset(current); current = null; });
}

['#services', '#barbers', '#products'].forEach((sel) => {
  const grid = document.querySelector(sel);
  if (grid) bindTilt(grid, '[data-tilt]');
});
