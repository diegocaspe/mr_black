import { api } from '../../api.js';
import { emptyState, fmtDateTime, html, loading, money, render, statusBadge } from '../../ui.js';
import { openSaleDetail } from '../shared.js';

export default async function purchasesView(root, { params }) {
  render(root, html`<div class="page-head"><div><h2>Mis compras</h2><p>Comprobantes de productos y servicios pagados.</p></div>
    <a href="#/tienda" class="btn btn-gold"><i class="fa-solid fa-store" aria-hidden="true"></i> Ir a la tienda</a></div><div id="pl" class="panel"></div>`);
  const box = root.querySelector('#pl');
  const load = async () => {
    render(box, loading());
    try {
      const res = await api.get('/sales', { page_size: 100 });
      render(box, res.items.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Comprobante</th><th>Fecha</th><th>Detalle</th><th>Método</th><th>Estado</th><th class="text-right">Total</th><th class="text-right">Acciones</th></tr></thead>
        <tbody>${res.items.map((s) => html`<tr><td data-label="Comprobante" class="bold">${s.receipt_code}</td><td data-label="Fecha">${fmtDateTime(s.created_at)}</td>
          <td data-label="Detalle">${s.items.map((i) => `${i.description} ×${i.quantity}`).join(', ')}</td><td data-label="Método">${s.payment_method_name}</td>
          <td data-label="Estado">${statusBadge(s.status)}</td><td data-label="Total" class="text-right bold">${money(s.total)}</td>
          <td data-label="" class="cell-actions"><a class="btn btn-dark btn-xs" href="${api.url(`/sales/${s.id}/receipt.pdf`, { download: true })}" aria-label="Descargar comprobante ${s.receipt_code}"><i class="fa-solid fa-download"></i> PDF</a>
            <button type="button" class="btn btn-ghost btn-xs" data-view="${s.id}">Detalle</button></td></tr>`)}</tbody></table></div>`
        : emptyState('fa-bag-shopping', 'Aún no tienes compras.'));
    } catch (err) { render(box, emptyState('fa-triangle-exclamation', err.message)); }
  };
  box.addEventListener('click', (e) => { const v = e.target.closest('[data-view]'); if (v) openSaleDetail(Number(v.dataset.view), load); });
  await load();
  if (params[0]) openSaleDetail(Number(params[0]), load);
}
