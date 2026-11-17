/**
 * Smoke to Power - Formulario para enviar datos de prueba a /api/sensor
 */

const SENSOR_URL = '/api/sensor';
const AUTO_SEND_DEBOUNCE_MS = 300;

const $ = (sel) => document.querySelector(sel);
const form = $('#sendForm');
const filterInput = $('#filter');
const powerInput = $('#power');
const filterOut = $('#filterOut');
const powerOut = $('#powerOut');
const autoSend = $('#autoSend');
const intervalSel = $('#interval');
const sendBtn = $('#sendBtn');
const result = $('#result');

let debounceTimer = null;
let continuousTimer = null;
let sending = false;

function readValues() {
  return {
    filter: Number(filterInput.value),
    power: Number(powerInput.value)
  };
}

function showResult(kind, message) {
  result.className = 'result' + (kind ? ' ' + kind : '');
  result.textContent = message;
}

function timeNow() {
  return new Date().toLocaleTimeString('es-ES');
}

async function sendReading() {
  if (sending) return; // evita solapar envíos (p. ej. envío continuo lento)
  const body = readValues();
  if (!Number.isFinite(body.filter) || !Number.isFinite(body.power)) {
    showResult('err', 'Valores inválidos.');
    return;
  }

  sending = true;
  sendBtn.disabled = true;
  try {
    const res = await fetch(SENSOR_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const json = await res.json().catch(() => ({}));

    if (res.ok && json.ok) {
      const r = json.received || {};
      const modo = r.simulation_mode ? 'simulación aún activa' : 'datos reales';
      showResult('ok',
        `✔ ${timeNow()} · Enviado: filtro ${body.filter.toFixed(1)} % · ${body.power.toFixed(1)} W ` +
        `→ dashboard: ${Number(r.filter_obstruction).toFixed(1)} % · ${modo}`
      );
    } else {
      showResult('err', `✖ ${timeNow()} · Error ${res.status}: ${json.error || 'respuesta no válida'}`);
    }
  } catch (err) {
    showResult('err', `✖ ${timeNow()} · Sin conexión con el servidor (${err.message})`);
  } finally {
    sending = false;
    sendBtn.disabled = false;
  }
}

function updateOutputs() {
  filterOut.textContent = Number(filterInput.value).toFixed(1) + ' %';
  powerOut.textContent = Number(powerInput.value).toFixed(1) + ' W';
}

function scheduleAutoSend() {
  if (!autoSend.checked) return;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(sendReading, AUTO_SEND_DEBOUNCE_MS);
}

function restartContinuous() {
  clearInterval(continuousTimer);
  continuousTimer = null;
  const ms = Number(intervalSel.value);
  if (ms > 0) {
    continuousTimer = setInterval(sendReading, ms);
    sendReading();
  }
}

filterInput.addEventListener('input', () => { updateOutputs(); scheduleAutoSend(); });
powerInput.addEventListener('input', () => { updateOutputs(); scheduleAutoSend(); });
intervalSel.addEventListener('change', restartContinuous);
form.addEventListener('submit', (e) => {
  e.preventDefault();
  sendReading();
});

updateOutputs();
