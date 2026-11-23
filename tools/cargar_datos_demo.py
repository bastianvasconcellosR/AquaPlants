"""Carga datos de demostración vía API (sin acceso directo a la base): sistemas, cultivos, dispositivos,
umbrales, mediciones históricas con algunas desviaciones y registros de bitácora.
Es idempotente en lo estructural (no duplica sistemas/cultivos/dispositivos ya existentes por nombre/código).
Uso:
  python tools/cargar_datos_demo.py --url https://TU-APP.onrender.com --admin-clave CLAVE_ADMIN \
      [--encargado-clave Cultivo2026aq] [--dias 3]
Solo biblioteca estándar. Las mediciones se envían con la API Key de cada dispositivo nuevo."""
import argparse, json, math, random, sys, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

ap = argparse.ArgumentParser()
ap.add_argument("--url", required=True)
ap.add_argument("--admin-email", default="admin@aquaplants.cl")
ap.add_argument("--admin-clave", required=True)
ap.add_argument("--encargado-email", default="encargado@aquaplants.cl")
ap.add_argument("--encargado-clave", default="Cultivo2026aq")
ap.add_argument("--dias", type=int, default=3)
a = ap.parse_args()
BASE = a.url.rstrip("/") + "/api/v1"
random.seed(2026)

def http(metodo, ruta, cuerpo=None, token=None, key=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    if key: h["X-API-Key"] = key
    r = urllib.request.Request(BASE + ruta, method=metodo, headers=h, data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(r, timeout=90) as x:
            return x.status, json.loads(x.read() or b"null")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except Exception: return e.code, None

def login(email, clave):
    st, js = http("POST", "/auth/login", {"email": email, "clave": clave})
    if st != 200: sys.exit(f"No se pudo iniciar sesión como {email}: {st} {js}")
    return js["token"]

UMBRALES = {"ph": (5.5, 6.8), "temperatura_agua": (18, 26), "caudal": (0.5, 5), "conductividad_ec": (1.0, 2.5), "humedad_ambiente": (40, 85)}
PERFIL = {"ph": (6.2, 0.25), "temperatura_agua": (22, 1.6), "caudal": (2.5, 0.5), "conductividad_ec": (1.7, 0.3), "humedad_ambiente": (62, 9)}
SISTEMAS = [("Invernadero Sur", "Sector sur, galpón 2"), ("Sala de Germinación", "Laboratorio, piso 1")]
CULTIVOS = [("Invernadero Sur", "Tomate cherry", "Solanum lycopersicum", "2026-09-10"), ("Invernadero Sur", "Pimentón rojo", "Capsicum annuum", "2026-09-22"),
            ("Invernadero Sur", "Frutilla aeropónica", "Fragaria x ananassa", "2026-10-05"), ("Sala de Germinación", "Almácigos de lechuga", "Lactuca sativa", "2026-11-02"),
            ("Sala de Germinación", "Cilantro", "Coriandrum sativum", "2026-11-09"), ("Sala de Germinación", "Menta", "Mentha spicata", "2026-11-12")]
DISPOSITIVOS = [("AB-003", "Controlador Invernadero A", "Invernadero Sur", ["ph", "temperatura_agua", "caudal"]),
                ("AB-004", "Controlador Invernadero B", "Invernadero Sur", ["conductividad_ec", "humedad_ambiente"]),
                ("AB-005", "Controlador Germinación", "Sala de Germinación", ["ph", "temperatura_agua", "humedad_ambiente"])]
BITACORA = [("Tomate cherry", "Riego", "Se ajustó el caudal de la línea 2 tras revisar la bomba."), ("Tomate cherry", "Fertilización", "Se agregó solución nutritiva A+B, EC objetivo 1,8 mS/cm."),
            ("Pimentón rojo", "Poda", "Se retiraron hojas basales para mejorar la ventilación."), ("Frutilla aeropónica", "Revisión", "Raíces sanas, boquillas de nebulización limpias."),
            ("Almácigos de lechuga", "Siembra", "Siembra de 200 plántulas en bandejas de germinación."), ("Cilantro", "Control de plagas", "Sin presencia de pulgón; se mantiene monitoreo semanal.")]

t = login(a.admin_email, a.admin_clave)
def existentes(ruta, campo):
    st, js = http("GET", ruta, token=t)
    return {f[campo]: f for f in (js or [])}

sis = existentes("/sistemas", "nombre")
for n, u in SISTEMAS:
    if n not in sis:
        st, js = http("POST", "/sistemas", {"nombre": n, "ubicacion": u}, t); sis[n] = {"id": js["id"]}; print("sistema", n, st)
ex_umb = {(u["id_sistema"], u["variable"]) for u in (http("GET", "/umbrales", token=t)[1] or [])}
for n, _ in SISTEMAS:
    for v, (lo, hi) in UMBRALES.items():
        if (sis[n]["id"], v) not in ex_umb:
            st, _js = http("POST", "/umbrales", {"id_sistema": sis[n]["id"], "variable": v, "minimo": lo, "maximo": hi}, t)
cul = existentes("/cultivos", "nombre")
for s, n, e, f in CULTIVOS:
    if n not in cul:
        st, js = http("POST", "/cultivos", {"id_sistema": sis[s]["id"], "nombre": n, "especie": e, "fecha_inicio": f}, t); cul[n] = {"id": js["id"]}; print("cultivo", n, st)
disp = existentes("/dispositivos", "codigo"); claves = {}
for cod, nom, s, vs in DISPOSITIVOS:
    if cod not in disp:
        st, js = http("POST", "/dispositivos", {"id_sistema": sis[s]["id"], "codigo": cod, "nombre": nom, "variables": vs}, t)
        if st == 201: claves[cod] = (js["api_key"], vs); print("dispositivo", cod, st)
        else: print("dispositivo", cod, "error", st, js)
    else:
        print("dispositivo", cod, "ya existía: sin clave, se omiten sus mediciones")

ahora = datetime.now(timezone.utc).replace(microsecond=0)
total = 0
for cod, (key, vs) in claves.items():
    for v in vs:
        mu, sd = PERFIL[v]; lo, hi = UMBRALES[v]; med = []
        n = a.dias * 24 * 6  # una lectura cada 10 minutos
        exc = random.randrange(n // 3, n - 30)  # una excursión puntual por serie, solo en algunas
        for i in range(n):
            ts = ahora - timedelta(minutes=10 * (n - i))
            val = mu + sd * math.sin(i / 40.0) * 0.8 + random.gauss(0, sd * 0.15)
            if cod == "AB-003" and v == "ph" and exc <= i < exc + 3: val = hi + 0.9                 # pH alto a mitad de período
            if cod == "AB-004" and v == "conductividad_ec" and n - 14 <= i < n - 11: val = lo - 0.5  # EC baja reciente
            if cod == "AB-005" and v == "humedad_ambiente" and n // 2 <= i < n // 2 + 3: val = hi + 6  # humedad alta
            med.append({"variable": v, "valor": round(val, 2), "marca_tiempo": ts.strftime("%Y-%m-%dT%H:%M:%SZ")})
        for k in range(0, len(med), 500):
            st, js = http("POST", "/mediciones/lote", {"mediciones": med[k:k + 500]}, key=key)
            if st not in (200, 201): print("lote", cod, v, "error", st, js); break
            total += len(med[k:k + 500])
print("mediciones enviadas:", total)

# Estados variados de alertas: una resuelta con causa, una en proceso y el resto pendientes
if claves:
    _, pend = http("GET", "/alertas?estado=Pendiente", token=t)
    pend = sorted([x for x in (pend or []) if x["dispositivo"] in claves], key=lambda x: x["creada_en"])
    if pend:
        http("PATCH", f"/alertas/{pend[0]['id']}", {"estado": "Resuelta", "causa": "Se corrigió la dosificación de la solución y el valor volvió al rango."}, t)
    if len(pend) > 1:
        http("PATCH", f"/alertas/{pend[1]['id']}", {"estado": "En proceso"}, t)
    print("alertas gestionadas:", min(len(pend), 2), "de", len(pend))

te = login(a.encargado_email, a.encargado_clave) if (a.encargado_clave and claves) else None  # bitácora solo en la primera carga
if te:
    ok = 0
    for c, acc, det in BITACORA:
        if c in cul:
            st, _js = http("POST", "/bitacora", {"id_cultivo": cul[c]["id"], "accion": acc, "detalle": det}, te); ok += st == 201
    print("registros de bitácora:", ok)
print("\nAPI Keys de los dispositivos nuevos (se muestran una sola vez):")
for cod, (key, _) in claves.items(): print(" ", cod, key)
