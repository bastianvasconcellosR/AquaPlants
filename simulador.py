#!/usr/bin/env python3
"""Simulador de dispositivos AquaBrain.

Envía mediciones a la API como lo haría el hardware real (con API Key), con búfer local:
si la API no responde, guarda las lecturas y las reenvía por lote al reconectar (CU10).
Solo usa la biblioteca estándar.

Ejemplos:
  python simulador.py --url http://localhost:8000 --clave AB-001=aq_1_xxxx --clave AB-002=aq_2_xxxx
  python simulador.py --escenario ph_alto --ciclos 3
  python simulador.py --escenario corte --ciclos 6      # simula caída de red y reenvío por lote
  python simulador.py --escenario corte --ciclos 30 --ciclos-corte 20 --intervalo 5   # corte de ~100 s: dispara la alerta de desconexión
  python simulador.py --clave-archivo demo_keys.json --intervalo 5
"""
import argparse
import json
import math
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PERFIL = {  # variable: (centro, amplitud de oscilación normal, dispositivo)
    "AB-001": {"ph": (6.15, 0.25), "temperatura_agua": (22.0, 1.2), "caudal": (2.7, 0.4)},
    "AB-002": {"conductividad_ec": (1.75, 0.2), "humedad_ambiente": (62.0, 6.0)},
}
PERFIL_GENERICO = {**PERFIL["AB-001"], **PERFIL["AB-002"]}  # dispositivos creados por el usuario: las 5 variables
ESCENARIOS = {
    "normal": {},
    "ph_alto": {"ph": 7.9},
    "temperatura_alta": {"temperatura_agua": 31.0},
    "caudal_bajo": {"caudal": 0.1},
    "ec_baja": {"conductividad_ec": 0.4},
    "dato_erroneo": {"ph": 99.0},  # fuera del rango físico: la API debe rechazarlo
    "corte": {},  # sin anomalía en valores; el corte se simula en la red
}


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enviar(url, clave, ruta, cuerpo, timeout=8):
    req = urllib.request.Request(url + "/api/v1" + ruta, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-API-Key": clave})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def lectura(cod, var, centro, amp, i, forzado):
    if var in forzado:   # el escenario aplica a esa variable en cualquier dispositivo que la tenga
        return forzado[var]
    return round(centro + amp * math.sin(i / 6) + random.uniform(-amp * 0.15, amp * 0.15), 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--clave", action="append", default=[], metavar="CODIGO=API_KEY")
    ap.add_argument("--clave-archivo", help="JSON {codigo: api_key} (lo genera la BD de demostración)")
    ap.add_argument("--escenario", choices=ESCENARIOS, default="normal")
    ap.add_argument("--intervalo", type=float, default=30, help="segundos entre lecturas (por defecto 30)")
    ap.add_argument("--ciclos", type=int, default=0, help="0 = infinito")
    ap.add_argument("--ciclos-corte", type=int, default=3, help="escenario corte: cuántos ciclos seguidos (desde el 2.º) sin red")
    a = ap.parse_args()

    claves = {}
    if a.clave_archivo:
        claves.update(json.load(open(a.clave_archivo)))
    for kv in a.clave:
        k, v = kv.split("=", 1)
        claves[k] = v
    if not claves:
        ap.error("falta al menos una API Key (--clave o --clave-archivo)")

    forzado = ESCENARIOS[a.escenario]
    buffer = {c: [] for c in claves}
    i = 0
    while a.ciclos == 0 or i < a.ciclos:
        i += 1
        # el escenario "corte" deja sin red --ciclos-corte ciclos (desde el 2.º) y luego reconecta
        sin_red = a.escenario == "corte" and 2 <= i <= 1 + a.ciclos_corte
        ahora = datetime.now(timezone.utc)
        for cod, clave in claves.items():
            for var, (centro, amp) in PERFIL.get(cod, PERFIL_GENERICO).items():
                buffer[cod].append({"variable": var, "valor": lectura(cod, var, centro, amp, i, forzado),
                                    "marca_tiempo": iso(ahora)})
            pend = buffer[cod]
            if sin_red:
                print(f"[{iso(ahora)}] {cod}: SIN RED – {len(pend)} lecturas en búfer local")
                continue
            if len(pend) > 2 * len(PERFIL.get(cod, PERFIL_GENERICO)):   # hay acumuladas: envío por lote
                st, r = enviar(a.url, clave, "/mediciones/lote", {"mediciones": pend[:500]})
                print(f"[{iso(ahora)}] {cod}: lote de {len(pend[:500])} -> HTTP {st} {r}")
                if st in (200, 201, 422):
                    del pend[:500]
                continue
            for m in list(pend):
                st, r = enviar(a.url, clave, "/mediciones", m)
                print(f"[{iso(ahora)}] {cod} {m['variable']}={m['valor']} -> HTTP {st} {r if st >= 400 or r.get('alerta') else ''}")
                if st in (201, 409, 422):
                    pend.remove(m)
        if a.ciclos == 0 or i < a.ciclos:
            time.sleep(a.intervalo)


if __name__ == "__main__":
    main()
