# Smoke to Power – Dashboard IoT

Aplicación web para monitorear en tiempo real:

- **Calidad del filtro de humo** (0-100 % de obstrucción)
- **Generación de energía** del módulo termoeléctrico (W y kWh del día)

Diseñada para recibir datos de un **ESP32** vía Wi-Fi.

## Características

- Dashboard con 2 tarjetas grandes en tiempo real
- Colores del filtro: **Verde** (Limpio) · **Amarillo** (Sucio) · **Rojo** (Bloqueado)
- Gráficos históricos (Chart.js, incluido localmente) de las últimas 24 h
- Alerta crítica cuando la obstrucción ≥ 80 %
- **Modo Simulación** (datos realistas cada 5 s) para probar sin hardware
- Endpoint REST listo para el ESP32
- **Backend sin dependencias de Python** (solo librería estándar)

## Cómo arrancar

### Opción 1: Python

```bash
cd smoke-to-power
python3 server.py
```

### Opción 2: Docker Compose

```bash
docker compose up -d --build   # construir y levantar
docker compose logs -f         # ver logs
docker compose down            # detener
```

Abre en el navegador: **http://localhost:5000**

> El modo simulación se inicia automáticamente.
> Puedes detenerlo/reanudarlo con el botón del dashboard.

## API para el ESP32

```http
POST /api/sensor
Content-Type: application/json

{
  "filter": 45.2,   // % obstrucción (0-100)
  "power": 18.7     // Watts actuales (números, no texto)
}
```

Al recibir datos reales se detiene automáticamente la simulación.
Si `filter` o `power` faltan o no son números, responde `400`.

### Otros endpoints

| Método | Ruta              | Descripción                                                        |
|--------|-------------------|--------------------------------------------------------------------|
| GET    | `/api/status`     | Estado actual                                                      |
| GET    | `/api/history`    | Historial de las últimas 24 h, muestreado a 300 puntos (`?points=N`, máx. 2000) |
| POST   | `/api/simulation` | `{"action": "start"}` o `"stop"`                                   |
| POST   | `/api/reset`      | Reinicia energía, valores e historial                              |

Todos los `POST` requieren `Content-Type: application/json` (responden `415` si no).

> **Seguridad:** la API no tiene autenticación. Úsala solo en una red local de confianza y no expongas el puerto 5000 a internet.

## Ejemplo de código ESP32 (Arduino)

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* ssid     = "TU_WIFI";
const char* password = "TU_PASSWORD";
const char* serverUrl = "http://IP_DE_TU_PC:5000/api/sensor";

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
}

void loop() {
  float filterPct = leerSensorFiltro();   // 0-100
  float powerW   = leerSensorPotencia();  // Watts

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<128> doc;
    doc["filter"] = filterPct;
    doc["power"]  = powerW;

    String body;
    serializeJson(doc, body);
    int code = http.POST(body);
    Serial.printf("POST status: %d\n", code);
    http.end();
  }
  delay(5000);  // cada 5 segundos
}
```

## Umbrales del filtro

| Rango     | Estado     | Color            |
|-----------|------------|------------------|
| 0 – 44 %  | Limpio     | Verde            |
| 45 – 79 % | Sucio      | Amarillo         |
| ≥ 80 %    | Bloqueado  | Rojo + Alerta    |

## Estructura del proyecto

```
smoke-to-power/
├── server.py            # Backend (Python stdlib)
├── Dockerfile
├── docker-compose.yml
├── templates/
│   └── index.html
└── static/
    ├── css/style.css
    └── js/
        ├── app.js
        └── chart.umd.min.js   # Chart.js 4.4.1 (local)
```

---
Smoke to Power · IoT Dashboard
