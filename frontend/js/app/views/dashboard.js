import { api } from '../../api.js';
import { emptyState, fmtDateTime, html, loading, money, render, statusBadge } from '../../ui.js';
import { barChart } from '../charts.js';

export default async function dashboard(root, { user }) {
  render(root, loading('Cargando indicadores…'));
  let d;
  try {
    d = await api.get('/reports/dashboard');
  } catch (err) {
    render(root, emptyState('fa-triangle-exclamation', err.message));
    return;
  }
  const maxSvc = Math.max(1, ...d.top_services.map((s) => s.count));
  const maxBar = Math.max(1, ...d.top_barbers.map((s) => s.count));
  const methods = d.payment_methods_month.filter((m) => Number(m.amount) > 0);

  render(root, html`
    <div class="page-head"><div><h2>Hola, ${user.full_name.split(' ')[0]}</h2><p>Resumen de la operación de Mr Black al ${new Intl.DateTimeFormat('es-PE', { dateStyle: 'long', timeZone: 'America/Lima' }).format(new Date())}.</p></div>
      <div class="flex gap-2 wrap"><a href="#/citas" class="btn btn-gold"><i class="fa-solid fa-calendar-plus" aria-hidden="true"></i> Registrar cita</a>
      <a href="#/caja" class="btn btn-dark"><i class="fa-solid fa-cash-register" aria-hidden="true"></i> Venta de mostrador</a></div></div>

    <section class="kpis" aria-label="Indicadores">
      ${kpi('Ventas del día', money(d.sales_today.total), `${d.sales_today.sales_count} venta(s)`, 'fa-sack-dollar')}
      ${kpi('Ventas del mes', money(d.sales_month.total), `Servicios ${money(d.sales_month.services)} · Productos ${money(d.sales_month.products)}`, 'fa-chart-line')}
      ${kpi('Citas de hoy', d.appointments_today.total, `${d.appointments_today.CONFIRMADA} confirmadas · ${d.appointments_today.ATENDIDA} atendidas`, 'fa-calendar-day')}
      ${kpi('Citas por confirmar', d.pending_appointments, 'Pendientes a futuro', 'fa-hourglass-half', d.pending_appointments > 0)}
      ${kpi('Clientes', d.clients, `${d.new_clients_month} nuevo(s) este mes`, 'fa-users')}
      ${kpi('Productos activos', d.active_products, `${d.low_stock.length} con stock bajo`, 'fa-box-open', d.low_stock.length > 0)}
      ${kpi('Servicios por cobrar', d.unpaid_services, 'Citas atendidas sin cobro', 'fa-cash-register', d.unpaid_services > 0)}
      ${kpi('Pedidos por cobrar', d.pending_orders, 'Pago en local pendiente', 'fa-store', d.pending_orders > 0)}
    </section>

    <div class="grid mt-6" style="grid-template-columns:minmax(0,2fr) minmax(0,1fr)" data-two>
      <section class="panel" aria-labelledby="ch-income">
        <div class="panel-head"><h3 class="panel-title" id="ch-income">Ingresos de los últimos 14 días</h3><span class="xs faint">Ventas pagadas</span></div>
        <div class="panel-pad"><div class="chart-box"><canvas id="income-chart" role="img" aria-label="Gráfico de ingresos diarios de los últimos 14 días"></canvas></div>
          <details class="mt-3"><summary class="small muted">Ver datos en tabla</summary>
            <div class="table-wrap mt-2"><table class="table"><thead><tr><th>Fecha</th><th class="text-right">Ingresos</th></tr></thead>
            <tbody>${d.income_last_14_days.map((x) => html`<tr><td>${x.date}</td><td class="text-right">${money(x.amount)}</td></tr>`)}</tbody></table></div></details></div>
      </section>
      <section class="panel" aria-labelledby="ch-alerts">
        <div class="panel-head"><h3 class="panel-title" id="ch-alerts"><i class="fa-solid fa-triangle-exclamation gold" aria-hidden="true"></i> Alertas de stock</h3><a href="#/inventario" class="small">Inventario</a></div>
        <div class="panel-pad">${d.low_stock.length ? d.low_stock.map((p) => html`<div class="list-row"><div><div class="bold small">${p.name}</div>
          <div class="xs faint">Mínimo ${p.min_stock}</div></div><span class="badge ${p.status === 'AGOTADO' ? 'b-danger' : 'b-warn'}">${p.status === 'AGOTADO' ? 'Agotado' : `${p.stock} unid.`}</span></div>`)
          : emptyState('fa-circle-check', 'No hay productos bajo el mínimo.')}</div>
      </section>
    </div>

    <div class="grid grid-3 mt-6">
      <section class="panel"><div class="panel-head"><h3 class="panel-title">Servicios más solicitados</h3><span class="xs faint">30 días</span></div>
        <div class="panel-pad">${d.top_services.length ? d.top_services.map((s) => rankRow(s.name, `${s.count} cita(s)`, s.count / maxSvc)) : emptyState('fa-scissors', 'Sin datos.')}</div></section>
      <section class="panel"><div class="panel-head"><h3 class="panel-title">Barberos con más citas</h3><span class="xs faint">30 días</span></div>
        <div class="panel-pad">${d.top_barbers.length ? d.top_barbers.map((b) => rankRow(b.name, `${b.count} cita(s) · ${b.attended} atendida(s)`, b.count / maxBar)) : emptyState('fa-user-tie', 'Sin datos.')}</div></section>
      <section class="panel"><div class="panel-head"><h3 class="panel-title">Métodos de pago del mes</h3></div>
        <div class="panel-pad">${methods.length ? html`<div class="chart-box" style="height:200px"><canvas id="methods-chart" role="img" aria-label="Ingresos por método de pago"></canvas></div>
          ${methods.map((m) => html`<div class="list-row small"><span>${m.name}</span><b>${money(m.amount)} · ${m.count}</b></div>`)}` : emptyState('fa-credit-card', 'Sin pagos este mes.')}</div></section>
    </div>

    <section class="panel mt-6"><div class="panel-head"><h3 class="panel-title">Próximas citas</h3><a href="#/citas" class="small">Ver todas</a></div>
      ${d.upcoming.length ? html`<div class="table-wrap"><table class="table responsive"><thead><tr><th>Fecha y hora</th><th>Cliente</th><th>Barbero</th><th>Servicio</th><th>Estado</th></tr></thead>
        <tbody>${d.upcoming.map((a) => html`<tr><td data-label="Fecha">${fmtDateTime(a.start_at)}</td><td data-label="Cliente">${a.client}</td>
          <td data-label="Barbero">${a.barber}</td><td data-label="Servicio">${a.service}</td><td data-label="Estado">${statusBadge(a.status)}</td></tr>`)}</tbody></table></div>`
        : emptyState('fa-calendar', 'No hay próximas citas.')}</section>`);

  barChart(root.querySelector('#income-chart'), d.income_last_14_days.map((x) => x.date.slice(5).split('-').reverse().join('/')),
    d.income_last_14_days.map((x) => Number(x.amount)), { money: true });
  if (methods.length) {
    barChart(root.querySelector('#methods-chart'), methods.map((m) => m.name), methods.map((m) => Number(m.amount)), { money: true, horizontal: true });
  }
  const two = root.querySelector('[data-two]');
  const mq = window.matchMedia('(max-width: 1024px)');
  const apply = () => { two.style.gridTemplateColumns = mq.matches ? '1fr' : 'minmax(0,2fr) minmax(0,1fr)'; };
  mq.addEventListener('change', apply);
  apply();
}

function kpi(label, value, sub, icon, alert = false) {
  return html`<div class="panel kpi ${alert ? 'alert' : ''}"><div><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>
    <div class="kpi-sub">${sub}</div></div><span class="kpi-icon"><i class="fa-solid ${icon}" aria-hidden="true"></i></span></div>`;
}

function rankRow(name, detail, ratio) {
  return html`<div class="mb-4"><div class="flex justify-between small"><span class="bold">${name}</span><span class="muted">${detail}</span></div>
    <div class="bar-track mt-1" aria-hidden="true"><div class="bar-fill" style="width:${Math.round(ratio * 100)}%"></div></div></div>`;
}
