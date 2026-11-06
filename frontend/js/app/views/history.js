import { api } from '../../api.js';
import { emptyState, fmtDate, fmtLongDate, html, loading, money, render, statusBadge } from '../../ui.js';

export default async function historyView(root) {
  render(root, loading());
  try {
    const [appts, sales] = await Promise.all([
      api.get('/appointments', { status: 'ATENDIDA', sort: 'fecha', order: 'desc', page_size: 100 }),
      api.get('/sales', { page_size: 100 }),
    ]);
    const spent = sales.items.filter((s) => s.status === 'PAGADA').reduce((t, s) => t + Number(s.total), 0);
    render(root, html`<div class="page-head"><div><h2>Mi historial</h2><p>Tus servicios atendidos y compras anteriores.</p></div></div>
      <div class="kpis mb-6">
        <div class="panel kpi"><div><div class="kpi-label">Servicios atendidos</div><div class="kpi-value">${appts.total}</div></div><span class="kpi-icon"><i class="fa-solid fa-scissors"></i></span></div>
        <div class="panel kpi"><div><div class="kpi-label">Compras</div><div class="kpi-value">${sales.total}</div></div><span class="kpi-icon"><i class="fa-solid fa-bag-shopping"></i></span></div>
        <div class="panel kpi"><div><div class="kpi-label">Total pagado</div><div class="kpi-value">${money(spent)}</div></div><span class="kpi-icon"><i class="fa-solid fa-sack-dollar"></i></span></div>
      </div>
      <div class="grid grid-2" style="align-items:start">
        <section class="panel"><div class="panel-head"><h3 class="panel-title"><i class="fa-solid fa-scissors gold" aria-hidden="true"></i> Servicios</h3></div><div class="panel-pad">
          ${appts.items.length ? appts.items.map((a) => html`<div class="list-row"><div><div class="bold">${a.service.name}</div>
            <div class="xs faint">${fmtLongDate(a.start_at)} · ${a.barber.full_name}</div></div><span class="gold bold">${money(a.price)}</span></div>`)
            : emptyState('fa-scissors', 'Sin servicios atendidos todavía.')}</div></section>
        <section class="panel"><div class="panel-head"><h3 class="panel-title"><i class="fa-solid fa-bag-shopping gold" aria-hidden="true"></i> Compras</h3><a href="#/compras" class="small">Ver comprobantes</a></div><div class="panel-pad">
          ${sales.items.length ? sales.items.map((s) => html`<div class="list-row"><div><div class="bold small">${s.items.map((i) => `${i.description} ×${i.quantity}`).join(', ')}</div>
            <div class="xs faint">${fmtDate(s.created_at)} · ${s.payment_method_name}</div></div><div class="text-right"><div class="gold bold">${money(s.total)}</div>${statusBadge(s.status)}</div></div>`)
            : emptyState('fa-bag-shopping', 'Sin compras todavía.')}</div></section>
      </div>`);
  } catch (err) { render(root, emptyState('fa-triangle-exclamation', err.message)); }
}
