import { api } from '../../api.js';
import { addToCart, loadCart, onCartChange, openCart } from '../../components/cart.js';
import { openProductDetail } from '../../components/product-detail.js';
import { debounce, emptyState, html, loading, money, productCover, raw, render } from '../../ui.js';

export default async function shopView(root) {
  const cats = await api.get('/categories');
  render(root, html`<div class="page-head"><div><h2>Tienda</h2><p>Compra productos y paga en línea o en el local.</p></div>
      <button type="button" class="btn btn-gold" data-cart><i class="fa-solid fa-cart-shopping" aria-hidden="true"></i> Carrito <span class="cart-count" data-count hidden>0</span></button></div>
    <div class="toolbar mb-6"><div class="field"><label for="sh-q" class="sr-only">Buscar</label><input id="sh-q" class="input" type="search" placeholder="Buscar producto…" maxlength="60"></div>
      <div class="field"><label for="sh-c" class="sr-only">Categoría</label><select id="sh-c" class="select"><option value="">Todas las categorías</option>
      ${cats.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select></div></div>
    <div id="sh" class="cards"></div>`);
  const grid = root.querySelector('#sh');
  const count = root.querySelector('[data-count]');
  onCartChange((c) => { if (!count.isConnected) return; count.textContent = c?.item_count || 0; count.hidden = !c?.item_count; });
  const load = async () => {
    render(grid, loading());
    try {
      const items = await api.get('/products', { q: root.querySelector('#sh-q').value.trim(), category_id: root.querySelector('#sh-c').value });
      render(grid, items.length ? html`${items.map((p) => {
        const out = p.stock <= 0;
        return html`<article class="panel product-card">
          <button type="button" class="product-hit" data-open="${p.id}" aria-label="Ver detalles de ${p.name}"></button>
          <div class="product-media"><span class="product-view" aria-hidden="true"><i class="fa-solid fa-eye"></i> Ver detalles</span>${productCover(p) ? html`<img src="${productCover(p)}" alt="${p.name}" loading="lazy">` : html`<i class="fa-solid ${p.icon}" aria-hidden="true"></i>`}</div>
          <div class="flex justify-between gap-3 mt-4"><h3>${p.name}</h3><span class="price nowrap">${money(p.price)}</span></div>
          <p class="desc">${p.description || ''}</p>
          <div class="flex justify-between items-center mt-4"><span class="stock-note ${out ? 'out' : p.stock_status === 'BAJO' ? 'low' : ''}">${out ? 'Agotado' : `Quedan ${p.stock}`}</span>
            <button type="button" class="btn btn-gold btn-sm" data-add="${p.id}" ${out ? raw('disabled') : ''}><i class="fa-solid fa-cart-plus" aria-hidden="true"></i> ${out ? 'Agotado' : 'Añadir'}</button></div></article>`;
      })}` : emptyState('fa-box-open', 'No hay productos disponibles.'));
    } catch (err) { render(grid, emptyState('fa-triangle-exclamation', err.message)); }
  };
  root.addEventListener('click', async (e) => {
    if (e.target.closest('[data-cart]')) { openCart(); return; }
    const open = e.target.closest('[data-open]') || (!e.target.closest('[data-add]') && e.target.closest('.product-card')?.querySelector('[data-open]'));
    if (open) { openProductDetail(Number(open.dataset.open), { onChange: load }); return; }
    const b = e.target.closest('[data-add]');
    if (!b || b.disabled) return;
    b.disabled = true;
    await addToCart(Number(b.dataset.add));
    load();
  });
  root.querySelector('#sh-q').addEventListener('input', debounce(load, 350));
  root.querySelector('#sh-c').addEventListener('change', load);
  onCartChange(() => { if (grid.isConnected && !document.querySelector('.drawer')) load(); });
  loadCart().catch(() => {});
  load();
}
