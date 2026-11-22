"""Prueba de carga con Locust (escenario de la ES2: 20 dispositivos × 5 sensores, 1 lectura/30 s).
Uso:  API_KEYS="aq_1_xxx,aq_2_yyy" locust -f tests/locustfile.py --host http://localhost:8000 -u 20 -r 5 -t 10m --headless
Cada usuario virtual = un dispositivo; necesita una API Key válida por dispositivo."""
import itertools, os, random
from datetime import datetime, timezone
from locust import HttpUser, between, task

KEYS = [k for k in os.getenv("API_KEYS", "").split(",") if k]
_it = itertools.cycle(KEYS or ["aq_0_sin-clave"])
VARS = {"ph": (5.8, 6.6), "temperatura_agua": (19, 25), "caudal": (1, 4), "conductividad_ec": (1.2, 2.3), "humedad_ambiente": (45, 80)}


class Dispositivo(HttpUser):
    wait_time = between(25, 35)

    def on_start(self):
        self.key = next(_it)

    @task
    def enviar(self):
        for var, (lo, hi) in VARS.items():
            self.client.post("/api/v1/mediciones", name="POST /mediciones", headers={"X-API-Key": self.key},
                             json={"variable": var, "valor": round(random.uniform(lo, hi), 2),
                                   "marca_tiempo": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
