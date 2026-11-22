"""Prueba de carga (PR). Solo biblioteca estándar.

Escenario de la ES2: 20 dispositivos × 5 sensores. En producción cada sensor reporta cada 30 s
(≈3,3 solicitudes/s en total); aquí se acelera a 1 lectura por sensor por segundo (100 solicitudes/s,
~30 veces la carga real) más 10 usuarios consultando el dashboard cada segundo (en producción, cada 30 s).
Criterios de aceptación: p95 < 500 ms y errores < 1 %.

  python -m tests.rendimiento [segundos]     (por defecto 40)
"""
import http.client
import json
import statistics
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from tests.base import ADMIN_EMAIL, ADMIN_PASS, Servidor

VARS = ["ph", "temperatura_agua", "caudal", "conductividad_ec", "humedad_ambiente"]
RANGO = {"ph": (5.5, 6.8), "temperatura_agua": (18, 26), "caudal": (0.5, 5), "conductividad_ec": (1, 2.5), "humedad_ambiente": (40, 85)}


def llamar(conn, metodo, ruta, cuerpo=None, token=None, key=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    if key: h["X-API-Key"] = key
    t0 = time.perf_counter()
    conn.request(metodo, "/api/v1" + ruta, json.dumps(cuerpo) if cuerpo is not None else None, h)
    r = conn.getresponse(); body = r.read()
    return r.status, (time.perf_counter() - t0) * 1000, body


def principal(duracion=40):
    srv = Servidor({"RATE_LIMIT_POR_MIN": "10000000"})
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=30)
        _, _, b = llamar(c, "POST", "/auth/login", {"email": ADMIN_EMAIL, "clave": ADMIN_PASS})
        tok = json.loads(b)["token"]
        _, _, b = llamar(c, "POST", "/sistemas", {"nombre": "Carga"}, tok); sid = json.loads(b)["id"]
        for v in VARS:
            llamar(c, "POST", "/umbrales", {"id_sistema": sid, "variable": v, "minimo": RANGO[v][0], "maximo": RANGO[v][1]}, tok)
        claves = []
        for i in range(20):
            _, _, b = llamar(c, "POST", "/dispositivos", {"id_sistema": sid, "codigo": f"LOAD-{i:02d}", "nombre": f"Carga {i}", "variables": VARS}, tok)
            claves.append(json.loads(b)["api_key"])

        lat_ing, lat_dash, errores, total = [], [], [], [0]
        lock = threading.Lock(); fin = time.time() + duracion

        def dispositivo(k):
            cn = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=30); n = 0
            origen = datetime.now(timezone.utc) - timedelta(seconds=duracion + 120)
            while time.time() < fin:
                inicio = time.time(); ts = (origen + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%SZ"); n += 1
                for v in VARS:
                    lo, hi = RANGO[v]
                    valor = round(lo + (hi - lo) * (0.2 + 0.6 * ((n * 7 + len(v)) % 10) / 10), 2)
                    st, ms, _ = llamar(cn, "POST", "/mediciones", {"variable": v, "valor": valor, "marca_tiempo": ts}, key=claves[k])
                    with lock:
                        total[0] += 1; lat_ing.append(ms)
                        if st != 201: errores.append(("ing", st))
                time.sleep(max(0, 1 - (time.time() - inicio)))

        def lector():
            cn = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=30)
            while time.time() < fin:
                inicio = time.time(); st, ms, _ = llamar(cn, "GET", "/dashboard/estado", token=tok)
                with lock:
                    total[0] += 1; lat_dash.append(ms)
                    if st != 200: errores.append(("dash", st))
                time.sleep(max(0, 1 - (time.time() - inicio)))

        hilos = [threading.Thread(target=dispositivo, args=(i,)) for i in range(20)] + [threading.Thread(target=lector) for _ in range(10)]
        t0 = time.time(); [h.start() for h in hilos]; [h.join() for h in hilos]; dur = time.time() - t0

        def resumen(l):
            l = sorted(l); q = lambda p: l[min(len(l) - 1, int(len(l) * p))]
            return {"n": len(l), "media_ms": round(statistics.mean(l), 1), "p50_ms": round(q(.5), 1), "p95_ms": round(q(.95), 1), "p99_ms": round(q(.99), 1), "max_ms": round(max(l), 1)}

        c2 = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=30)
        res = {"duracion_s": round(dur, 1), "solicitudes": total[0], "throughput_rps": round(total[0] / dur, 1),
               "errores": len(errores), "tasa_error_pct": round(100 * len(errores) / max(1, total[0]), 3), "detalle_errores": errores[:5],
               "ingesta": resumen(lat_ing), "dashboard": resumen(lat_dash)}
        res["cumple"] = res["ingesta"]["p95_ms"] < 500 and res["dashboard"]["p95_ms"] < 500 and res["tasa_error_pct"] < 1
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return res
    finally:
        srv.parar()


if __name__ == "__main__":
    r = principal(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
    import os
    os.makedirs("docs/evidencias", exist_ok=True)
    json.dump(r, open("docs/evidencias/rendimiento.json", "w"), indent=2, ensure_ascii=False)
