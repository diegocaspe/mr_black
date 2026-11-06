import { api } from '../../api.js';
import { $, emptyState, html, loading, money, render, setFieldError, showErrors, clearErrors, todayISO } from '../../ui.js';
import { rules, validateForm } from '../../validators.js';
import { barChart } from '../charts.js';

export default async function financeView(root) {
  render(root, html`<div class="page-head"><div><h2>Finanzas y reportes</h2><p>Ingresos cobrados por servicios y productos en el rango seleccionado.</p></div></div>
    <form class="panel panel-pad filters" id="ff" novalidate>
      <div class="field"><label for="ff-from">Desde <span class="req">*</span></label><input id="ff-from" name="date_from" type="date" class="input" min="2000-01-01" max="2099-12-31" required value="${todayISO(-30)}"></div>
      <div class="field"><label for="ff-to">Hasta <span class="req">*</span></label><input id="ff-to" name="date_to" type="date" class="input" min="2000-01-01" max="2099-12-31" required value="${todayISO()}"></div>
      <div class="field"><button type="submit" class="btn btn-gold"><i class="fa-solid fa-calculator" aria-hidden="true"></i> Calcular reporte</button></div>
      <div class="field"><a class="btn btn-dark" id="ff-csv" href="#"><i class="fa-solid fa-file-csv" aria-hidden="true"></i> Exportar ventas CSV</a></div>
    </form>
    <div id="fr" class="mt-6"></div>`);
  const form = $('#ff', root);
  const out = $('#fr', root);
  const schema = {
    date_from: [rules.reportDate],
    date_to: [rules.reportDate, (v, f) => (f.elements.date_from.value && v < f.elements.date_from.value ? 'La fecha "Hasta" no puede ser anterior a "Desde".' : null)],
  };
  const valid = () => {
    // Un input date con año inválido (p. ej. 0001) también marca badInput/rangeUnderflow.
    const ok = validateForm(form, schema);
    for (const el of [form.elements.date_from, form.elements.date_to]) {
      if (el.validity.badInput || el.validity.rangeUnderflow || el.validity.rangeOverflow) {
        setFieldError(form, el.name, 'La fecha debe estar entre 01/01/2000 y 31/12/2099.');
        return false;
      }
    }
    return ok;
  };

  async function calculate() {
    clearErrors(form);
    if (!valid()) { render(out, ''); return; }
    const params = { date_from: form.elements.date_from.value, date_to: form.elements.date_to.value };
    $('#ff-csv', root).href = api.url('/reports/sales.csv', params);
    render(out, loading('Calculando…'));
    try {
      const r = await api.get('/reports/finance', params);
      const ap = r.appointments;
      render(out, html`<div class="kpis">
          ${kpi('Ingresos totales', money(r.income.total), `${r.income.sales_count} venta(s) cobrada(s)`, 'fa-sack-dollar')}
          ${kpi('Ingresos por servicios', money(r.income.services), 'Citas cobradas', 'fa-scissors')}
          ${kpi('Ingresos por productos', money(r.income.products), 'Tienda y mostrador', 'fa-box')}
          ${kpi('Ticket promedio', money(r.average_ticket), 'Por venta', 'fa-receipt')}
          ${kpi('Citas atendidas', ap.ATENDIDA, `${ap.total} cita(s) en el rango`, 'fa-user-check')}
          ${kpi('Canceladas / Pendientes', `${ap.CANCELADA} / ${ap.PENDIENTE}`, `${ap.CONFIRMADA} confirmada(s)`, 'fa-hourglass-half')}
          ${kpi('Pedidos por cobrar', money(r.pending_orders_amount), 'Pago en local', 'fa-store')}
        </div>
        ${r.daily.length ? html`<section class="panel mt-6"><div class="panel-head"><h3 class="panel-title">Ingresos diarios</h3></div>
          <div class="panel-pad"><div class="chart-box"><canvas id="fin-chart" role="img" aria-label="Ingresos diarios del rango"></canvas></div></div></section>` : ''}
        <div class="grid grid-2 mt-6">
          ${table('Ingresos por método de pago', ['Método', 'Operaciones', 'Monto'], r.by_method.map((m) => [m.name, m.count, money(m.amount)]))}
          ${table('Productos más vendidos', ['Producto', 'Unidades', 'Monto'], r.top_products.map((p) => [p.name, p.quantity, money(p.amount)]))}
          ${table('Servicios más solicitados', ['Servicio', 'Citas'], r.top_services.map((s) => [s.name, s.count]))}
          ${table('Barberos con más citas', ['Barbero', 'Citas', 'Atendidas'], r.top_barbers.map((b) => [b.name, b.count, b.attended]))}
        </div>`);
      if (r.daily.length) barChart($('#fin-chart', out), r.daily.map((d) => d.date.slice(5).split('-').reverse().join('/')), r.daily.map((d) => Number(d.amount)), { money: true });
    } catch (err) {
      if (err.fields && Object.keys(err.fields).length) showErrors(form, err.fields, err.message);
      render(out, emptyState('fa-triangle-exclamation', err.message));
    }
  }
  form.addEventListener('submit', (e) => { e.preventDefault(); calculate(); });
  $('#ff-csv', root).addEventListener('click', (e) => { if (!valid()) e.preventDefault(); });
  calculate();
}

function kpi(label, value, sub, icon) {
  return html`<div class="panel kpi"><div><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-sub">${sub}</div></div>
    <span class="kpi-icon"><i class="fa-solid ${icon}" aria-hidden="true"></i></span></div>`;
}

function table(title, headers, rows) {
  return html`<section class="panel"><div class="panel-head"><h3 class="panel-title">${title}</h3></div>
    ${rows.length ? html`<div class="table-wrap"><table class="table"><thead><tr>${headers.map((h, i) => html`<th class="${i ? 'text-right' : ''}">${h}</th>`)}</tr></thead>
      <tbody>${rows.map((r) => html`<tr>${r.map((c, i) => html`<td class="${i ? 'text-right' : ''}">${c}</td>`)}</tr>`)}</tbody></table></div>` : emptyState('fa-chart-simple', 'Sin datos en el rango.')}</section>`;
}
