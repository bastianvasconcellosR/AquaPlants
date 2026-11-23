#!/usr/bin/env python3
"""Simulador de dispositivos AquaBrain.

Envía mediciones a la API como lo haría el hardware real (con API Key), con búfer local:
si la API no responde, guarda las lecturas y las reenvía por lote al reconectar (CU10).
Solo usa la biblioteca estándar.

Ejemplos:
  python simulador.py --url http://localhost:8000 --clave AB-001=aq_1_xxxx --clave AB-002=aq_2_xxxx
  python simulador.py --escenario ph_alto --ciclos 3
  python simulador.py --escenario aleatorio --intervalo 10 --prob 0.03   # operación continua con alertas espontáneas
  python simulador.py --escenario corte --ciclos 6      # simula caída de red y reenvío por lote
  python simulador.py --escenario corte --ciclos 30 --ciclos-corte 20 --intervalo 5   # corte de ~100 s: dispara la alerta de desconexión
  python simulador.py --clave-archivo demo_keys.json --intervalo 5
  python simulador.py --todos --admin-clave TU_CLAVE --escenario aleatorio --intervalo 10   # todos los dispositivos
  Corte manual durante la ejecución:  echo AB-003> corte.txt   (AB-003 pierde la conexión)
                                      del corte.txt             (se reconecta y reenvía lo acumulado por lote)
"""
import argparse
import json
import math
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
    "aleatorio": {},  # operación normal con anomalías espontáneas (ver --prob): alertas "reales" que nadie programó
}
# Valores fuera de rango (por debajo o por encima de los umbrales de demostración) para las anomalías aleatorias
FUERA = {"ph": (5.0, 7.7), "temperatura_agua": (15.0, 29.5), "caudal": (0.2, 6.0),
         "conductividad_ec": (0.5, 3.0), "humedad_ambiente": (30.0, 92.0)}


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


def llamar(url, metodo, ruta, cuerpo=None, token=None, timeout=15):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url + "/api/v1" + ruta, method=metodo, headers=h,
                                 data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def claves_de_todos(url, email, clave):
    """Modo --todos: inicia sesión como Administrador y obtiene una clave nueva para cada dispositivo activo.
    Ojo: regenerar revoca la clave anterior de cada dispositivo."""
    st, js = llamar(url, "POST", "/auth/login", {"email": email, "clave": clave})
    if st != 200:
        raise SystemExit(f"No se pudo iniciar sesión como {email}: HTTP {st} {js}")
    token = js["token"]
    claves = {}
    for d in (llamar(url, "GET", "/dispositivos", token=token)[1] or []):
        if not d.get("activo", True):
            continue
        st, r = llamar(url, "POST", f"/dispositivos/{d['id']}/regenerar-clave", token=token)
        if st in (200, 201):
            claves[d["codigo"]] = r["api_key"]
        else:
            print(f"  {d['codigo']}: no se pudo regenerar la clave (HTTP {st})")
    return claves


def dispositivos_cortados(ruta):
    """Corte manual: si existe el archivo, los códigos que contiene (separados por espacio, coma o línea) quedan sin red;
    un archivo vacío corta a todos. Al borrar el archivo, el dispositivo se reconecta y reenvía lo acumulado por lote."""
    try:
        txt = open(ruta, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    codigos = {x.strip().upper() for x in txt.replace(",", " ").split() if x.strip()}
    return codigos or {"*"}


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
    ap.add_argument("--prob", type=float, default=0.03, help="escenario aleatorio: probabilidad por ciclo y variable de iniciar una anomalía (por defecto 0.03)")
    ap.add_argument("--todos", action="store_true", help="obtiene una clave nueva para TODOS los dispositivos (requiere --admin-clave) y los simula a todos; revoca las claves anteriores")
    ap.add_argument("--admin-email", default="admin@aquaplants.cl")
    ap.add_argument("--admin-clave", help="contraseña del Administrador (solo para --todos)")
    ap.add_argument("--archivo-corte", default="corte.txt", help="corte manual: si este archivo existe, los dispositivos que nombra (o todos si está vacío) quedan sin red hasta que se borre (por defecto corte.txt)")
    ap.add_argument("--ciclos-corte", type=int, default=3, help="escenario corte: cuántos ciclos seguidos (desde el 2.º) sin red")
    a = ap.parse_args()

    claves = {}
    if a.clave_archivo:
        claves.update(json.load(open(a.clave_archivo)))
    for kv in a.clave:
        k, v = kv.split("=", 1)
        claves[k] = v
    if a.todos:
        if not a.admin_clave:
            ap.error("--todos necesita --admin-clave")
        claves.update(claves_de_todos(a.url.rstrip("/"), a.admin_email, a.admin_clave))
        print("Dispositivos simulados:", ", ".join(sorted(claves)))
    if not claves:
        ap.error("falta al menos una API Key (--clave, --clave-archivo o --todos)")

    forzado = ESCENARIOS[a.escenario]
    buffer = {c: [] for c in claves}
    ignoradas = set()   # (dispositivo, variable) que la API informó como no registradas: no se vuelven a enviar
    anomalia = {}       # (dispositivo, variable) -> [ciclos restantes, valor fuera de rango]
    conocidos = set()   # dispositivos cuyas variables ya se validaron con un primer envío individual
    url = a.url

    def ciclo(cod, clave, i, ahora, sin_red, cortados):
        """Un ciclo de un dispositivo: genera sus lecturas y las envía en UN solo lote (o las guarda si no hay red)."""
        out = []
        for var, (centro, amp) in PERFIL.get(cod, PERFIL_GENERICO).items():
            if (cod, var) in ignoradas:
                continue
            valor = lectura(cod, var, centro, amp, i, forzado)
            if a.escenario == "aleatorio":
                k = (cod, var)
                if k not in anomalia and random.random() < a.prob:
                    anomalia[k] = [random.randint(2, 4), random.choice(FUERA[var])]
                    out.append(f"[{iso(ahora)}] {cod}: anomalía espontánea en {var} ({anomalia[k][1]}) durante {anomalia[k][0]} ciclos")
                if k in anomalia:
                    valor = anomalia[k][1]
                    anomalia[k][0] -= 1
                    if anomalia[k][0] <= 0:
                        del anomalia[k]
            buffer[cod].append({"variable": var, "valor": valor, "marca_tiempo": iso(ahora)})
        pend = buffer[cod]
        corte_manual = bool(cortados) and ("*" in cortados or cod.upper() in cortados)
        if sin_red or corte_manual:
            out.append(f"[{iso(ahora)}] {cod}: SIN RED – {len(pend)} lecturas en búfer local")
            return out
        if cod not in conocidos:   # primer contacto: envío individual para aprender qué variables mide este dispositivo
            for m in list(pend):
                st, r = enviar(url, clave, "/mediciones", m)
                if st == 422 and "sensor activo" in str(r):
                    ignoradas.add((cod, m["variable"])); pend.remove(m); continue
                out.append(f"[{iso(ahora)}] {cod} {m['variable']}={m['valor']} -> HTTP {st} {r if st >= 400 or r.get('alerta') else ''}")
                if st in (201, 409, 422):
                    pend.remove(m)
            conocidos.add(cod)
            return out
        lote = pend[:500]
        if not lote:
            return out
        st, r = enviar(url, clave, "/mediciones/lote", {"mediciones": lote})
        if st == 422 and "sensor activo" in str(r):   # cambió la configuración del dispositivo: se vuelve a aprender
            conocidos.discard(cod)
            out.append(f"[{iso(ahora)}] {cod}: la API rechazó una variable; se revalidan sus sensores")
            return out
        vals = ", ".join(f"{m['variable']}={m['valor']}" for m in lote[-len(PERFIL.get(cod, PERFIL_GENERICO)):])
        cola = f" · alertas nuevas: {r['alertas']}" if st < 400 and r.get("alertas") else (f" {r}" if st >= 400 else "")
        nv = len(PERFIL.get(cod, PERFIL_GENERICO))
        if len(lote) > nv:   # había lecturas acumuladas de un corte: reenvío por lote
            out.append(f"[{iso(ahora)}] {cod}: lote de {len(lote)} lecturas acumuladas (recuperación tras el corte) -> HTTP {st}{cola}")
        else:
            out.append(f"[{iso(ahora)}] {cod}: {len(lote)} lecturas en un lote ({vals}) -> HTTP {st}{cola}")
        if st in (200, 201, 422):
            del pend[:500]
        return out

    i = 0
    with ThreadPoolExecutor(max_workers=max(1, len(claves))) as pool:
        while a.ciclos == 0 or i < a.ciclos:
            i += 1
            t0 = time.time()
            # el escenario "corte" deja sin red --ciclos-corte ciclos (desde el 2.º) y luego reconecta
            sin_red = a.escenario == "corte" and 2 <= i <= 1 + a.ciclos_corte
            ahora = datetime.now(timezone.utc)
            cortados = dispositivos_cortados(a.archivo_corte)
            # todos los dispositivos envían a la vez (como equipos independientes), no uno detrás de otro
            futuros = [pool.submit(ciclo, cod, clave, i, ahora, sin_red, cortados) for cod, clave in claves.items()]
            for f in futuros:
                for linea in f.result():
                    print(linea, flush=True)
            if a.ciclos == 0 or i < a.ciclos:
                time.sleep(max(0.0, a.intervalo - (time.time() - t0)))


if __name__ == "__main__":
    main()
