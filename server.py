#!/usr/bin/env python3
"""
Smoke to Power - Backend sin dependencias externas
Usa solo la librería estándar de Python (http.server + threading)
"""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from collections import deque
import threading
import time
import random
import math
import json
import os

# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------
# Ventana de retención del historial (por tiempo, no por cantidad).
HISTORY_WINDOW = timedelta(hours=24)
# Tope de seguridad de memoria: 24 h a una lectura cada 5 s son ~17 280 puntos.
MAX_HISTORY = 50_000
# Número máximo de puntos que se envían al frontend en /api/history.
DEFAULT_CHART_POINTS = 300
MAX_CHART_POINTS = 2000

history = deque(maxlen=MAX_HISTORY)

# Valores iniciales (también se usan al reiniciar)
INITIAL_FILTER_PCT = 25.0
INITIAL_POWER_W = 12.5

# Si no llega ningún dato real del ESP32 en este tiempo, se considera "sin datos"
SENSOR_TIMEOUT_S = 15

current_state = {
    "filter_obstruction": INITIAL_FILTER_PCT,
    "power_watts": INITIAL_POWER_W,
    "energy_today_kwh": 0.0,
    "last_update": None,
    "alert_active": False,
    "simulation_mode": True
}

simulation_running = False
simulation_thread = None
sim_generation = 0          # identifica la "versión" vigente del hilo de simulación
sim_lock = threading.Lock()
last_energy_timestamp = None
last_real_at = None         # momento de la última lectura real del ESP32
lock = threading.Lock()

PORT = 5000
ROOT = os.path.dirname(os.path.abspath(__file__))


def calculate_energy_increment(power_w: float, seconds: float) -> float:
    return (power_w * seconds) / 3_600_000


def parse_number(value) -> float:
    """Convierte a float finito o lanza ValueError/TypeError."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("no numérico")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("no finito")
    return result


def add_reading(filter_pct: float, power_w: float, source: str = "simulation"):
    global last_energy_timestamp, last_real_at

    now = datetime.now(timezone.utc)
    filter_pct = max(0.0, min(100.0, float(filter_pct)))
    power_w = max(0.0, float(power_w))

    with lock:
        # Cambio de día (UTC): reiniciar energía ANTES de acumular la nueva lectura
        if last_energy_timestamp is not None and last_energy_timestamp.date() != now.date():
            current_state["energy_today_kwh"] = 0.0

        if last_energy_timestamp is not None:
            delta_s = (now - last_energy_timestamp).total_seconds()
            if 0 < delta_s < 3600:
                current_state["energy_today_kwh"] += calculate_energy_increment(power_w, delta_s)

        last_energy_timestamp = now
        if source == "sensor":
            last_real_at = now
        current_state["filter_obstruction"] = round(filter_pct, 1)
        current_state["power_watts"] = round(power_w, 2)
        current_state["last_update"] = iso_utc(now)
        current_state["alert_active"] = filter_pct >= 80.0

        history.append({
            "timestamp": iso_utc(now),
            "filter": round(filter_pct, 1),
            "power": round(power_w, 2),
            "energy_today": round(current_state["energy_today_kwh"], 4)
        })

        # Descartar lecturas más antiguas que la ventana de 24 h
        cutoff = now - HISTORY_WINDOW
        while history and parse_timestamp(history[0]["timestamp"]) < cutoff:
            history.popleft()


def get_data_source() -> dict:
    """Modo que muestra la UI: 'simulation', 'real' o 'waiting'."""
    with lock:
        simulating = current_state["simulation_mode"]
        last = last_real_at
    if simulating:
        return {"data_source": "simulation", "seconds_since_real": None}
    if last is None:
        return {"data_source": "waiting", "seconds_since_real": None}
    age = (datetime.now(timezone.utc) - last).total_seconds()
    mode = "real" if age <= SENSOR_TIMEOUT_S else "waiting"
    return {"data_source": mode, "seconds_since_real": int(age)}


def iso_utc(dt: datetime) -> str:
    """ISO 8601 en UTC terminado en 'Z' (aware, sin deprecaciones)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_timestamp(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def downsample(items: list, max_points: int) -> list:
    """Reduce la lista a ~max_points conservando el último punto."""
    if len(items) <= max_points:
        return items
    step = math.ceil(len(items) / max_points)
    sampled = items[::step]
    if sampled[-1] is not items[-1]:
        sampled.append(items[-1])
    return sampled


def simulation_loop(generation: int):
    filter_base = 20.0
    power_base = 15.0

    # El hilo sigue solo mientras esté activa la simulación Y no haya
    # arrancado una generación más nueva (evita hilos duplicados).
    while simulation_running and generation == sim_generation:
        filter_base += random.uniform(-1.5, 2.0) + 0.08
        filter_base = max(5.0, min(98.0, filter_base))

        flow_factor = 1.0 - (filter_base / 150.0)
        power = power_base * flow_factor + random.uniform(-3.0, 4.0)
        power = max(2.0, min(45.0, power))
        power += 2.5 * math.sin(time.time() / 40.0)

        add_reading(filter_base, power)
        time.sleep(5)


def start_simulation():
    global simulation_running, simulation_thread, sim_generation
    with sim_lock:
        if simulation_running:
            return
        simulation_running = True
        sim_generation += 1
        generation = sim_generation
        current_state["simulation_mode"] = True
        simulation_thread = threading.Thread(
            target=simulation_loop, args=(generation,), daemon=True
        )
        simulation_thread.start()


def stop_simulation():
    global simulation_running
    with sim_lock:
        simulation_running = False
        current_state["simulation_mode"] = False


# ---------------------------------------------------------------------------
# Handler HTTP
# ---------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, format, *args):
        # Silenciar logs de acceso normales
        if not str(args[0]).startswith('"GET /api'):
            return
        print(f"[{self.log_date_time_string()}] {args[0]}")

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            # Servir el template
            self.path = "/templates/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        if path == "/enviar-data":
            # Formulario para enviar datos de prueba a /api/sensor
            self.path = "/templates/enviar.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        if path.startswith("/static/"):
            return SimpleHTTPRequestHandler.do_GET(self)

        if path == "/api/status":
            with lock:
                data = dict(current_state)
                count = len(history)
            data.update(get_data_source())
            return self._send_json({"ok": True, "data": data, "history_count": count})

        if path == "/api/history":
            query = parse_qs(parsed.query)
            try:
                max_points = int(query.get("points", [DEFAULT_CHART_POINTS])[0])
            except ValueError:
                max_points = DEFAULT_CHART_POINTS
            max_points = max(10, min(MAX_CHART_POINTS, max_points))

            cutoff = datetime.now(timezone.utc) - HISTORY_WINDOW
            with lock:
                recent = [h for h in history if parse_timestamp(h["timestamp"]) >= cutoff]
            return self._send_json({"ok": True, "data": downsample(recent, max_points)})

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Solo JSON: un formulario HTML de otro sitio no puede enviar
        # application/json sin preflight CORS, así que se bloquea el CSRF.
        content_type = self.headers.get("Content-Type", "")
        if not content_type.split(";")[0].strip().lower() == "application/json":
            return self._send_json({"ok": False, "error": "Content-Type debe ser application/json"}, 415)

        if path == "/api/sensor":
            body = self._read_json()
            if "filter" not in body or "power" not in body:
                return self._send_json({"ok": False, "error": "Missing 'filter' or 'power'"}, 400)
            try:
                filter_pct = parse_number(body["filter"])
                power_w = parse_number(body["power"])
            except (TypeError, ValueError):
                return self._send_json(
                    {"ok": False, "error": "'filter' y 'power' deben ser números finitos"}, 400
                )

            if current_state["simulation_mode"]:
                stop_simulation()

            add_reading(filter_pct, power_w, source="sensor")
            with lock:
                data = dict(current_state)
            return self._send_json({"ok": True, "received": data})

        if path == "/api/simulation":
            body = self._read_json()
            action = body.get("action", "start")
            if action == "start":
                start_simulation()
                return self._send_json({"ok": True, "message": "Simulación iniciada", "simulation_mode": True})
            elif action == "stop":
                stop_simulation()
                return self._send_json({"ok": True, "message": "Simulación detenida", "simulation_mode": False})
            return self._send_json({"ok": False, "error": "action debe ser start o stop"}, 400)

        if path == "/api/reset":
            global last_energy_timestamp, last_real_at
            with lock:
                history.clear()
                current_state["energy_today_kwh"] = 0.0
                current_state["filter_obstruction"] = INITIAL_FILTER_PCT
                current_state["power_watts"] = INITIAL_POWER_W
                current_state["alert_active"] = False
                last_energy_timestamp = None
                last_real_at = None
            return self._send_json({"ok": True, "message": "Estado reiniciado"})

        self.send_error(404, "Not Found")


def main():
    # Semilla + simulación
    add_reading(22.0, 14.5)
    start_simulation()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("=" * 60)
    print("  SMOKE TO POWER - Dashboard IoT")
    print(f"  → http://localhost:{PORT}")
    print("  Endpoint ESP32: POST /api/sensor")
    print('  Body: {"filter": 45.2, "power": 18.7}')
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
        stop_simulation()
        server.shutdown()


if __name__ == "__main__":
    main()
