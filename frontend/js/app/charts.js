/** Gráficos con Chart.js: una sola serie en dorado, barras finas, cuadrícula discreta y tooltip. */
import { money } from '../ui.js';

const GOLD = '#B08D57';
const GRID = 'rgba(255,255,255,0.06)';
const TICK = '#a3a3a3';

function whenChartReady() {
  return new Promise((resolve) => {
    if (window.Chart) return resolve(window.Chart);
    const t = setInterval(() => { if (window.Chart) { clearInterval(t); resolve(window.Chart); } }, 50);
    setTimeout(() => { clearInterval(t); resolve(null); }, 8000);
  });
}

export async function barChart(canvas, labels, values, { money: isMoney = false, horizontal = false } = {}) {
  if (!canvas) return null;
  const Chart = await whenChartReady();
  if (!Chart || !canvas.isConnected) return null;
  const fmt = (v) => (isMoney ? money(v) : String(v));
  const valueAxis = { grid: { color: GRID }, border: { display: false }, ticks: { color: TICK, callback: (v) => (isMoney ? `S/ ${v}` : v) }, beginAtZero: true };
  const catAxis = { grid: { display: false }, border: { color: '#3b3b3b' }, ticks: { color: TICK, autoSkip: true, maxRotation: 0 } };
  return new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets: [{ data: values, backgroundColor: GOLD, hoverBackgroundColor: '#C6A46E', borderRadius: 4, borderSkipped: 'start', maxBarThickness: horizontal ? 18 : 28 }] },
    options: {
      indexAxis: horizontal ? 'y' : 'x',
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: '#171717', borderColor: '#3A3633', borderWidth: 1, titleColor: '#F1E8D8', bodyColor: '#cfcfcf',
          displayColors: false, callbacks: { label: (ctx) => fmt(horizontal ? ctx.parsed.x : ctx.parsed.y) } },
      },
      scales: horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis },
    },
  });
}
