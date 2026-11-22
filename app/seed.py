"""Datos iniciales. Se ejecuta solo si la base está vacía.

- Siempre: roles y un Administrador (clave desde ADMIN_PASSWORD, o generada e impresa una vez).
- Con SEED_DEMO=1: supervisor y encargado de ejemplo, un sistema con dos cultivos,
  dos dispositivos con sensores, umbrales por defecto y 24 h de mediciones de prueba.
"""
import json
import math
import random
import secrets
from datetime import timedelta

from . import config, db, security

DEMO_CLAVES = {
    "supervisor@aquaplants.cl": ("Supervisor", "Super2026aq", "Marcela Soto"),
    "encargado@aquaplants.cl": ("Encargado", "Cultivo2026aq", "Diego Fuentes"),
}


def run(c):
    if c.one("SELECT COUNT(*) AS n FROM usuario")["n"] > 0:
        return
    ahora = db.utcnow()
    roles = {r["nombre"]: r["id"] for r in c.all("SELECT id, nombre FROM rol")}

    clave_admin = config.ADMIN_PASSWORD
    generada = False
    if not clave_admin:
        clave_admin = "Aq" + secrets.token_urlsafe(9) + "7"
        generada = True
    c.insert("usuario", {
        "nombre": "Administrador", "email": config.ADMIN_EMAIL, "hash_clave": security.hash_clave(clave_admin),
        "id_rol": roles["Administrador"], "activo": True, "intentos_fallidos": 0,
        "creado_en": db.to_iso(ahora),
    })
    if generada:
        print(f"[seed] Administrador creado: {config.ADMIN_EMAIL} / {clave_admin}  (cámbiela)")

    if not config.SEED_DEMO:
        return

    for email, (rol, clave, nombre) in DEMO_CLAVES.items():
        c.insert("usuario", {
            "nombre": nombre, "email": email, "hash_clave": security.hash_clave(clave),
            "id_rol": roles[rol], "activo": True, "intentos_fallidos": 0, "creado_en": db.to_iso(ahora),
        })

    sid = c.insert("sistema", {"nombre": "AquaBrain Torre 1", "ubicacion": "Invernadero Norte", "activo": True})
    cultivos = [
        ("Torre A - Lechugas", "Lactuca sativa", "2026-08-01"),
        ("Torre B - Albahaca", "Ocimum basilicum", "2026-08-15"),
    ]
    for n, e, f in cultivos:
        c.insert("cultivo", {"id_sistema": sid, "nombre": n, "especie": e, "fecha_inicio": f, "activo": True})

    for var, (mn, mx) in config.UMBRALES_DEFECTO.items():
        c.insert("umbral", {"id_sistema": sid, "variable": var, "minimo": mn, "maximo": mx})

    defs = [
        ("AB-001", "Controlador Torre A", ["ph", "temperatura_agua", "caudal"]),
        ("AB-002", "Controlador Torre B", ["conductividad_ec", "humedad_ambiente"]),
    ]
    claves = {}
    sensores = []  # (id_sensor, variable)
    for codigo, nombre, variables in defs:
        did = c.insert("dispositivo", {
            "id_sistema": sid, "codigo": codigo, "nombre": nombre, "tipo": "controlador",
            "hash_api_key": "pendiente", "ultima_comunicacion": None, "activo": True,
        })
        key = security.generar_api_key(did)
        c.update("dispositivo", {"hash_api_key": security.hash_api_key(key)}, "id = ?", (did,))
        claves[codigo] = key
        for v in variables:
            sensores.append((c.insert("sensor", {
                "id_dispositivo": did, "variable": v, "unidad": config.UNIDADES[v], "activo": True}), v, did))

    # 24 h de mediciones de prueba (cada 5 min), con ruido determinista y dos excursiones fuera de umbral
    rnd = random.Random(2026)
    inicio = ahora - timedelta(hours=24)
    for idx, (sen, var, did) in enumerate(sensores):
        mn, mx = config.UMBRALES_DEFECTO[var]
        centro, amp = (mn + mx) / 2, (mx - mn) / 2
        filas = []
        for i in range(0, 24 * 12 + 1):
            t = inicio + timedelta(minutes=5 * i)
            v = centro + amp * 0.35 * math.sin(i / 20 + idx) + rnd.uniform(-amp * 0.12, amp * 0.12)
            if var == "ph" and 100 <= i <= 106:
                v = mx + 0.35  # excursión de pH
            filas.append((sen, round(v, 2), db.to_iso(t), db.to_iso(t)))
        c.many("INSERT INTO medicion (id_sensor, valor, marca_tiempo, recibido_en) VALUES (?,?,?,?)", filas)

    ph = next(s for s in sensores if s[1] == "ph")
    med = c.one("SELECT id, valor, marca_tiempo FROM medicion WHERE id_sensor = ? ORDER BY marca_tiempo LIMIT 1 OFFSET 100", (ph[0],))
    c.insert("alerta", {
        "id_dispositivo": ph[2], "id_sensor": ph[0], "id_medicion": med["id"], "tipo": "umbral",
        "severidad": "Advertencia", "mensaje": f"pH fuera de rango: {med['valor']} (permitido 5.5 a 6.8)",
        "valor": med["valor"], "estado": "Resuelta", "causa": "Ajuste de dosificación de ácido",
        "creada_en": db.iso(med["marca_tiempo"]), "actualizada_en": db.iso(med["marca_tiempo"]), "id_usuario": None,
    })

    if config.ENV != "prod":
        try:
            with open("demo_keys.json", "w") as fh:
                json.dump(claves, fh, indent=2)
        except OSError:
            pass
    for cod, k in claves.items():
        print(f"[seed] API Key de {cod}: {k}")
