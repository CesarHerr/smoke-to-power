#!/usr/bin/env python3
"""
Smoke to Power - Backend sin dependencias externas
Usa solo la librería estándar de Python (http.server + threading)
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timedelta
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
MAX_HISTORY = 300
history = deque(maxlen=MAX_HISTORY)

current_state = {
    "filter_obstruction": 25.0,
    "power_watts": 12.5,
    "energy_today_kwh": 0.0,
    "last_update": None,
    "alert_active": False,
    "simulation_mode": True
}

simulation_running = False
simulation_thread = None
last_energy_timestamp = None
lock = threading.Lock()

PORT = 5000
ROOT = os.path.dirname(os.path.abspath(__file__))


def calculate_energy_increment(power_w: float, seconds: float) -> float:
    return (power_w * seconds) / 3_600_000


def add_reading(filter_pct: float, power_w: float):
    global last_energy_timestamp

    now = datetime.utcnow()
    filter_pct = max(0.0, min(100.0, float(filter_pct)))
    power_w = max(0.0, float(power_w))

    with lock:
        if last_energy_timestamp is not None:
            delta_s = (now - last_energy_timestamp).total_seconds()
            if 0 < delta_s < 3600:
                current_state["energy_today_kwh"] += calculate_energy_increment(power_w, delta_s)

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
    global simulation_running
    filter_base = 20.0
    power_base = 15.0

    while simulation_running:
        filter_base += random.uniform(-1.5, 2.0) + 0.08
        filter_base = max(5.0, min(98.0, filter_base))

        flow_factor = 1.0 - (filter_base / 150.0)
        power = power_base * flow_factor + random.uniform(-3.0, 4.0)
        power = max(2.0, min(45.0, power))
        power += 2.5 * math.sin(time.time() / 40.0)

        add_reading(filter_base, power)
        time.sleep(5)


def start_simulation():
    global simulation_running, simulation_thread
    if not simulation_running:
        simulation_running = True
        current_state["simulation_mode"] = True
        simulation_thread = threading.Thread(target=simulation_loop, daemon=True)
        simulation_thread.start()


def stop_simulation():
    global simulation_running
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            # Servir el template
            self.path = "/templates/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        if path.startswith("/static/"):
            return SimpleHTTPRequestHandler.do_GET(self)

        if path == "/api/status":
            with lock:
                data = dict(current_state)
            return self._send_json({"ok": True, "data": data, "history_count": len(history)})

        if path == "/api/history":
            cutoff = datetime.utcnow() - timedelta(hours=24)
            with lock:
                recent = [
                    h for h in history
                    if datetime.fromisoformat(h["timestamp"].replace("Z", "")) >= cutoff
                ]
            return self._send_json({"ok": True, "data": list(recent)})

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/sensor":
            body = self._read_json()
            filter_pct = body.get("filter")
            power_w = body.get("power")
            if filter_pct is None or power_w is None:
                return self._send_json({"ok": False, "error": "Missing 'filter' or 'power'"}, 400)

            if current_state["simulation_mode"]:
                stop_simulation()

            add_reading(filter_pct, power_w)
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
            global history, last_energy_timestamp
            with lock:
                history.clear()
                current_state["energy_today_kwh"] = 0.0
                current_state["filter_obstruction"] = 25.0
                current_state["power_watts"] = 12.0
                current_state["alert_active"] = False
                last_energy_timestamp = None
            return self._send_json({"ok": True, "message": "Estado reiniciado"})

        self.send_error(404, "Not Found")


def main():
    # Semilla + simulación
    add_reading(22.0, 14.5)
    start_simulation()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
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
