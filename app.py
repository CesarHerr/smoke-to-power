"""
Smoke to Power - Backend Flask
Recibe datos de sensores ESP32 (filtro + termoelectricidad)
y sirve el dashboard con modo simulación.
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
from collections import deque
import threading
import time
import random
import math

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Almacenamiento en memoria (últimas 24 h ≈ 288 puntos si cada 5 min,
# pero guardamos cada lectura de simulación / sensor)
# ---------------------------------------------------------------------------
MAX_HISTORY = 288  # ~24 h si se guarda cada 5 min; en simulación cada 5 s
history = deque(maxlen=MAX_HISTORY)

# Estado actual
current_state = {
    "filter_obstruction": 25.0,      # %
    "power_watts": 12.5,             # W
    "energy_today_kwh": 0.0,         # kWh acumulado hoy
    "last_update": None,
    "alert_active": False,
    "simulation_mode": True
}

# Control de simulación
simulation_running = False
simulation_thread = None
last_energy_timestamp = None


def calculate_energy_increment(power_w: float, seconds: float) -> float:
    """Convierte potencia (W) * tiempo (s) a kWh."""
    return (power_w * seconds) / 3_600_000  # W·s → kWh


def add_reading(filter_pct: float, power_w: float):
    """Añade una lectura al historial y actualiza el estado."""
    global last_energy_timestamp

    now = datetime.utcnow()
    filter_pct = max(0.0, min(100.0, float(filter_pct)))
    power_w = max(0.0, float(power_w))

    # Acumular energía del día
    if last_energy_timestamp is not None:
        delta_s = (now - last_energy_timestamp).total_seconds()
        if delta_s > 0 and delta_s < 3600:  # evitar saltos grandes
            current_state["energy_today_kwh"] += calculate_energy_increment(power_w, delta_s)

    # Reset diario a medianoche UTC (simple)
    if last_energy_timestamp and last_energy_timestamp.date() != now.date():
        current_state["energy_today_kwh"] = 0.0

    last_energy_timestamp = now

    current_state["filter_obstruction"] = round(filter_pct, 1)
    current_state["power_watts"] = round(power_w, 2)
    current_state["last_update"] = now.isoformat() + "Z"
    current_state["alert_active"] = filter_pct >= 80.0

    history.append({
        "timestamp": now.isoformat() + "Z",
        "filter": round(filter_pct, 1),
        "power": round(power_w, 2),
        "energy_today": round(current_state["energy_today_kwh"], 4)
    })


def simulation_loop():
    """Genera datos realistas cada 5 segundos."""
    global simulation_running

    # Estado interno de la simulación para que no sea completamente aleatorio
    filter_base = 20.0
    power_base = 15.0
    trend = 0.3  # el filtro tiende a ensuciarse lentamente

    while simulation_running:
        # Filtro: camina aleatoriamente + tendencia lenta a ensuciarse
        filter_base += random.uniform(-1.5, 2.0) + trend * 0.05
        filter_base = max(5.0, min(98.0, filter_base))

        # Potencia: depende un poco del flujo (menos flujo → menos potencia)
        # y tiene variación natural
        flow_factor = 1.0 - (filter_base / 150.0)  # se reduce un poco con suciedad
        power = power_base * flow_factor + random.uniform(-3.0, 4.0)
        power = max(2.0, min(45.0, power))

        # Pequeña oscilación sinusoidal para parecer más real
        t = time.time()
        power += 2.5 * math.sin(t / 40.0)

        add_reading(filter_base, power)
        time.sleep(5)


def start_simulation():
    global simulation_running, simulation_thread
    if not simulation_running:
        simulation_running = True
        simulation_thread = threading.Thread(target=simulation_loop, daemon=True)
        simulation_thread.start()
        current_state["simulation_mode"] = True


def stop_simulation():
    global simulation_running
    simulation_running = False
    current_state["simulation_mode"] = False


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Estado actual + alertas."""
    return jsonify({
        "ok": True,
        "data": current_state,
        "history_count": len(history)
    })


@app.route("/api/history")
def api_history():
    """Historial de las últimas 24 h (o lo que haya)."""
    # Filtrar solo las últimas 24 h por si acaso
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent = [
        h for h in history
        if datetime.fromisoformat(h["timestamp"].replace("Z", "")) >= cutoff
    ]
    return jsonify({
        "ok": True,
        "data": list(recent)
    })


@app.route("/api/sensor", methods=["POST"])
def api_sensor():
    """
    Endpoint para el ESP32.
    Espera JSON: { "filter": 45.2, "power": 18.7 }
    """
    if not request.is_json:
        return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 400

    body = request.get_json()
    filter_pct = body.get("filter")
    power_w = body.get("power")

    if filter_pct is None or power_w is None:
        return jsonify({"ok": False, "error": "Missing 'filter' or 'power'"}), 400

    # Si llega dato real, detenemos la simulación automáticamente
    if current_state["simulation_mode"]:
        stop_simulation()

    add_reading(filter_pct, power_w)
    return jsonify({"ok": True, "received": current_state})


@app.route("/api/simulation", methods=["POST"])
def api_simulation():
    """Activa / desactiva el modo simulación."""
    body = request.get_json(silent=True) or {}
    action = body.get("action", "start")

    if action == "start":
        start_simulation()
        return jsonify({"ok": True, "message": "Simulación iniciada", "simulation_mode": True})
    elif action == "stop":
        stop_simulation()
        return jsonify({"ok": True, "message": "Simulación detenida", "simulation_mode": False})
    else:
        return jsonify({"ok": False, "error": "action debe ser 'start' o 'stop'"}), 400


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reinicia energía del día e historial (útil para demos)."""
    global history, last_energy_timestamp
    history.clear()
    current_state["energy_today_kwh"] = 0.0
    current_state["filter_obstruction"] = 25.0
    current_state["power_watts"] = 12.0
    current_state["alert_active"] = False
    last_energy_timestamp = None
    return jsonify({"ok": True, "message": "Estado reiniciado"})


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Semilla inicial + arrancar simulación por defecto
    add_reading(22.0, 14.5)
    start_simulation()

    print("=" * 60)
    print("  SMOKE TO POWER - Dashboard IoT")
    print("  http://localhost:5000")
    print("  Endpoint ESP32: POST /api/sensor  {\"filter\":45.2,\"power\":18.7}")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
