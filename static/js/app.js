/**
 * Smoke to Power - Frontend
 * Polling cada 3 s + Chart.js para históricos
 */

const POLL_MS = 3000;

// DOM
const $ = (sel) => document.querySelector(sel);
const filterValue = $('#filterValue');
const filterFill = $('#filterFill'); // no usado (conic-gradient)
const filterGauge = $('#filterGauge');
const filterStatus = $('#filterStatus');
const cardFilter = $('#cardFilter');
const powerValue = $('#powerValue');
const energyValue = $('#energyValue');
const alertBanner = $('#alertBanner');
const lastUpdate = $('#lastUpdate');
const simBadge = $('#simBadge');
const simText = $('#simText');
const btnSim = $('#btnSim');
const btnReset = $('#btnReset');

// Charts
let powerChart = null;
let filterChart = null;

function initCharts() {
  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#1a2330',
        titleColor: '#e8eef4',
        bodyColor: '#a0b0c0',
        borderColor: '#2a3a4a',
        borderWidth: 1,
        padding: 10,
        displayColors: false
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(30, 42, 54, 0.8)' },
        ticks: {
          color: '#6b7c8d',
          maxTicksLimit: 8,
          font: { size: 10, family: "'JetBrains Mono', monospace" }
        }
      },
      y: {
        grid: { color: 'rgba(30, 42, 54, 0.8)' },
        ticks: {
          color: '#6b7c8d',
          font: { size: 10, family: "'JetBrains Mono', monospace" }
        }
      }
    }
  };

  powerChart = new Chart($('#powerChart'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Potencia (W)',
        data: [],
        borderColor: '#00d4aa',
        backgroundColor: 'rgba(0, 212, 170, 0.12)',
        borderWidth: 2,
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        pointHoverRadius: 4
      }]
    },
    options: {
      ...commonOptions,
      scales: {
        ...commonOptions.scales,
        y: {
          ...commonOptions.scales.y,
          title: { display: false },
          suggestedMin: 0,
          suggestedMax: 50
        }
      }
    }
  });

  filterChart = new Chart($('#filterChart'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Obstrucción (%)',
        data: [],
        borderColor: '#38bdf8',
        backgroundColor: 'rgba(56, 189, 248, 0.12)',
        borderWidth: 2,
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        pointHoverRadius: 4
      }]
    },
    options: {
      ...commonOptions,
      scales: {
        ...commonOptions.scales,
        y: {
          ...commonOptions.scales.y,
          min: 0,
          max: 100,
          ticks: {
            ...commonOptions.scales.y.ticks,
            callback: (v) => v + '%'
          }
        }
      }
    }
  });
}

function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('es-ES', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

function formatChartLabel(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
}

function getFilterStatus(pct) {
  if (pct >= 80) return { label: 'BLOQUEADO', cls: 'blocked' };
  if (pct >= 45) return { label: 'SUCIO', cls: 'dirty' };
  return { label: 'LIMPIO', cls: 'clean' };
}

function updateUI(state) {
  const pct = state.filter_obstruction ?? 0;
  const power = state.power_watts ?? 0;
  const energy = state.energy_today_kwh ?? 0;

  // Filter gauge
  filterValue.textContent = pct.toFixed(1);
  filterGauge.style.setProperty('--pct', pct);

  // Color del gauge según umbral
  let colorStart = '#22c55e';
  if (pct >= 80) colorStart = '#ff4d4f';
  else if (pct >= 45) colorStart = '#f5c518';

  filterGauge.style.background = `conic-gradient(
    ${colorStart} 0deg,
    ${colorStart} ${pct * 3.6}deg,
    #1e2a36 ${pct * 3.6}deg
  )`;

  // Status pill
  const st = getFilterStatus(pct);
  filterStatus.textContent = st.label;
  filterStatus.className = 'status-pill ' + st.cls;

  cardFilter.className = 'card card-filter status-' + st.cls;

  // Energy
  powerValue.textContent = power.toFixed(1);
  energyValue.textContent = energy.toFixed(3);

  // Alert
  if (state.alert_active || pct >= 80) {
    alertBanner.hidden = false;
  } else {
    alertBanner.hidden = true;
  }

  // Last update
  lastUpdate.textContent = 'Actualizado: ' + formatTime(state.last_update);

  // Simulation badge
  if (state.simulation_mode) {
    simBadge.classList.remove('off');
    simText.textContent = 'Simulación ON';
  } else {
    simBadge.classList.add('off');
    simText.textContent = 'Datos reales';
  }
}

function updateCharts(history) {
  if (!history || !history.length) return;

  // Limitar a ~120 puntos para rendimiento (últimas ~10 min en simulación de 5s)
  const data = history.slice(-120);

  const labels = data.map(h => formatChartLabel(h.timestamp));
  const powers = data.map(h => h.power);
  const filters = data.map(h => h.filter);

  powerChart.data.labels = labels;
  powerChart.data.datasets[0].data = powers;
  powerChart.update('none');

  filterChart.data.labels = labels;
  filterChart.data.datasets[0].data = filters;
  filterChart.update('none');
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const json = await res.json();
    if (json.ok) updateUI(json.data);
  } catch (err) {
    console.error('Error status:', err);
  }
}

async function fetchHistory() {
  try {
    const res = await fetch('/api/history');
    const json = await res.json();
    if (json.ok) updateCharts(json.data);
  } catch (err) {
    console.error('Error history:', err);
  }
}

async function poll() {
  await Promise.all([fetchStatus(), fetchHistory()]);
}

async function toggleSimulation() {
  const isOn = !simBadge.classList.contains('off');
  const action = isOn ? 'stop' : 'start';
  try {
    const res = await fetch('/api/simulation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
    const json = await res.json();
    if (json.ok) {
      // refrescar inmediatamente
      await fetchStatus();
    }
  } catch (err) {
    console.error('Error simulation:', err);
  }
}

async function resetData() {
  if (!confirm('¿Reiniciar energía del día e historial?')) return;
  try {
    await fetch('/api/reset', { method: 'POST' });
    await poll();
  } catch (err) {
    console.error('Error reset:', err);
  }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  poll();
  setInterval(poll, POLL_MS);

  btnSim.addEventListener('click', toggleSimulation);
  btnReset.addEventListener('click', resetData);
});
