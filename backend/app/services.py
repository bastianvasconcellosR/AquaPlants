"""Lógica de negocio: ingesta, motor de alertas, estado del dashboard, respaldos."""
import glob
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import timedelta

from . import config, db

ESTADOS_ALERTA = ("Pendiente", "En proceso", "Resuelta")


# ---------------------------------------------------------------- auditoría
def auditar(c, usuario, accion, detalle=None, id_cultivo=None, categoria="auditoria"):
    c.insert("evento_bitacora", {
        "categoria": categoria, "id_usuario": usuario["id"] if usuario else None,
        "id_cultivo": id_cultivo, "accion": accion[:60], "detalle": (detalle or "")[:500],
        "creado_en": db.to_iso(db.utcnow()),
    })


def leer_config(c):
    """Intentos máximos de contraseña y minutos de bloqueo: valor guardado en la BD o, si no existe, el valor por defecto."""
    filas = {f["clave"]: f["valor"] for f in c.all("SELECT clave, valor FROM configuracion")}
    def num(k, defecto):
        try:
            return int(filas[k])
        except (KeyError, ValueError):
            return defecto
    return {"max_intentos": num("max_intentos", config.MAX_INTENTOS),
            "bloqueo_minutos": num("bloqueo_minutos", config.BLOQUEO_MINUTOS)}


# ---------------------------------------------------------------- alertas
def _severidad(valor, mn, mx):
    ancho = mx - mn
    desvio = (mn - valor) if valor < mn else (valor - mx)
    return "Crítica" if desvio > 0.25 * ancho else "Advertencia"


def evaluar_umbral(c, disp, sensor, medicion_id, valor):
    """Crea una alerta si el valor sale del umbral y no hay otra abierta para ese sensor."""
    u = c.one("SELECT minimo, maximo FROM umbral WHERE id_sistema = ? AND variable = ?",
              (disp["id_sistema"], sensor["variable"]))
    if not u or u["minimo"] <= valor <= u["maximo"]:
        return None
    abierta = c.one(
        "SELECT id FROM alerta WHERE id_sensor = ? AND tipo = 'umbral' AND estado <> 'Resuelta'", (sensor["id"],))
    if abierta:
        return None  # evita inundar de alertas repetidas mientras la anterior sigue abierta
    texto = (f"{config.NOMBRES.get(sensor['variable'], sensor['variable'])} fuera de rango: {valor} {sensor['unidad']} "
             f"(permitido {u['minimo']} a {u['maximo']})")
    # insert_ignore + índice único parcial: aunque dos solicitudes lleguen a la vez, queda una sola alerta abierta
    return c.insert_ignore("alerta", {
        "id_dispositivo": disp["id"], "id_sensor": sensor["id"], "id_medicion": medicion_id,
        "tipo": "umbral", "severidad": _severidad(valor, u["minimo"], u["maximo"]), "mensaje": texto,
        "valor": valor, "estado": "Pendiente", "creada_en": db.to_iso(db.utcnow()),
    })


def cerrar_desconexion(c, disp):
    """Si el dispositivo vuelve a comunicar, se cierra la alerta de desconexión abierta."""
    ahora = db.to_iso(db.utcnow())
    for a in c.all("SELECT id FROM alerta WHERE id_dispositivo = ? AND tipo = 'desconexion' AND estado <> 'Resuelta'",
                   (disp["id"],)):
        c.update("alerta", {"estado": "Resuelta", "causa": "Reconexión automática del dispositivo",
                            "actualizada_en": ahora}, "id = ?", (a["id"],))


# ---------------------------------------------------------------- ingesta
class ErrorIngesta(Exception):
    def __init__(self, status, mensaje):
        self.status, self.mensaje = status, mensaje


def _sensor_de(c, disp, variable):
    s = c.one("SELECT * FROM sensor WHERE id_dispositivo = ? AND variable = ?", (disp["id"], variable))
    if not s or not s["activo"]:
        raise ErrorIngesta(422, f"El dispositivo no tiene un sensor activo para '{variable}'")
    return s


def _insertar(c, sensor, valor, ts_iso, ahora_iso):
    """Devuelve id de medición o None si ya existía (sensor, marca_tiempo)."""
    cur = c.execute(
        "INSERT INTO medicion (id_sensor, valor, marca_tiempo, recibido_en) VALUES (?,?,?,?) "
        "ON CONFLICT (id_sensor, marca_tiempo) DO NOTHING",
        (sensor["id"], valor, ts_iso, ahora_iso))
    if cur.rowcount == 0:
        return None
    return c.one("SELECT id FROM medicion WHERE id_sensor = ? AND marca_tiempo = ?", (sensor["id"], ts_iso))["id"]


def recibir(c, disp, m):
    s = _sensor_de(c, disp, m.variable)
    ahora = db.utcnow()
    ts = db.to_iso(m.marca_tiempo or ahora)
    mid = _insertar(c, s, m.valor, ts, db.to_iso(ahora))
    if mid is None:
        raise ErrorIngesta(409, "Medición duplicada para ese sensor y marca de tiempo")
    alerta = evaluar_umbral(c, disp, s, mid, m.valor)
    c.update("dispositivo", {"ultima_comunicacion": db.to_iso(ahora)}, "id = ?", (disp["id"],))
    cerrar_desconexion(c, disp)
    return {"id": mid, "alerta": alerta}


def recibir_lote(c, disp, lote):
    """Transaccional: si una medición no corresponde a un sensor del dispositivo, no se guarda nada."""
    ahora = db.utcnow()
    sensores = {}
    for m in lote.mediciones:
        if m.variable not in sensores:
            sensores[m.variable] = _sensor_de(c, disp, m.variable)
    ins = dup = 0
    alertas = []
    for m in sorted(lote.mediciones, key=lambda x: x.marca_tiempo or ahora):
        s = sensores[m.variable]
        ts = db.to_iso(m.marca_tiempo or ahora)
        mid = _insertar(c, s, m.valor, ts, db.to_iso(ahora))
        if mid is None:
            dup += 1
            continue
        ins += 1
        a = evaluar_umbral(c, disp, s, mid, m.valor)
        if a:
            alertas.append(a)
    c.update("dispositivo", {"ultima_comunicacion": db.to_iso(ahora)}, "id = ?", (disp["id"],))
    cerrar_desconexion(c, disp)
    return {"recibidas": len(lote.mediciones), "insertadas": ins, "duplicadas": dup, "alertas": alertas}


# ---------------------------------------------------------------- estado del dashboard
def cultivos_por_sistema(c):
    """{id_sistema: [nombres de cultivos activos]}: relaciona cada cultivo con los dispositivos y alertas de su sistema."""
    r = {}
    for f in c.all("SELECT id_sistema, nombre FROM cultivo WHERE activo = ? ORDER BY id", (True,)):
        r.setdefault(f["id_sistema"], []).append(f["nombre"])
    return r


def estado(c):
    ahora = db.utcnow()
    limite = ahora - timedelta(seconds=config.OFFLINE_SEGUNDOS)
    disps = c.all("""SELECT d.id, d.codigo, d.nombre, d.ultima_comunicacion, d.id_sistema, s.nombre AS sistema
                     FROM dispositivo d JOIN sistema s ON s.id = d.id_sistema
                     WHERE d.activo = ? ORDER BY d.id""", (True,))
    cult_sis = cultivos_por_sistema(c)
    sensores = c.all("""
        SELECT se.id, se.id_dispositivo, se.variable, se.unidad, d.id_sistema,
               (SELECT m.valor FROM medicion m WHERE m.id_sensor = se.id ORDER BY m.marca_tiempo DESC LIMIT 1) AS valor,
               (SELECT m.marca_tiempo FROM medicion m WHERE m.id_sensor = se.id ORDER BY m.marca_tiempo DESC LIMIT 1) AS marca
        FROM sensor se JOIN dispositivo d ON d.id = se.id_dispositivo
        WHERE se.activo = ? AND d.activo = ? ORDER BY se.id""", (True, True))
    umbrales = {(u["id_sistema"], u["variable"]): u for u in c.all("SELECT * FROM umbral")}

    salida = []
    for d in disps:
        uc = db.iso(d["ultima_comunicacion"])
        online = bool(uc) and db.parse_iso(uc) >= limite
        if not online:
            _alerta_desconexion(c, d, uc)
        sens = []
        for s in (x for x in sensores if x["id_dispositivo"] == d["id"]):
            u = umbrales.get((s["id_sistema"], s["variable"]))
            cond = "sin datos"
            if s["valor"] is not None and u:
                cond = "normal" if u["minimo"] <= s["valor"] <= u["maximo"] else "fuera de rango"
            sens.append({"id": s["id"], "variable": s["variable"], "unidad": s["unidad"], "valor": s["valor"],
                         "marca_tiempo": db.iso(s["marca"]), "condicion": cond,
                         "minimo": u["minimo"] if u else None, "maximo": u["maximo"] if u else None})
        salida.append({"id": d["id"], "codigo": d["codigo"], "nombre": d["nombre"], "sistema": d["sistema"],
                       "conexion": "en línea" if online else "sin conexión", "ultima_comunicacion": uc,
                       "cultivos": cult_sis.get(d["id_sistema"], []), "sensores": sens})
    pend = c.one("SELECT COUNT(*) AS n FROM alerta WHERE estado = 'Pendiente'")["n"]
    proc = c.one("SELECT COUNT(*) AS n FROM alerta WHERE estado = 'En proceso'")["n"]
    return {"generado_en": db.to_iso(ahora), "dispositivos": salida,
            "alertas_pendientes": pend, "alertas_en_proceso": proc}


def _alerta_desconexion(c, d, uc):
    if uc is None:
        return  # nunca ha comunicado: no es una caída, es un equipo recién registrado
    ya = c.one("SELECT id FROM alerta WHERE id_dispositivo = ? AND tipo = 'desconexion' AND estado <> 'Resuelta'",
               (d["id"],))
    if ya:
        return
    c.insert_ignore("alerta", {
        "id_dispositivo": d["id"], "tipo": "desconexion", "severidad": "Crítica",
        "mensaje": f"{d['codigo']} sin comunicación desde {uc} (más de {config.OFFLINE_SEGUNDOS} s)",
        "estado": "Pendiente", "creada_en": db.to_iso(db.utcnow())})


# ---------------------------------------------------------------- respaldos
def _fernet():
    from cryptography.fernet import Fernet

    if config.BACKUP_KEY:
        return Fernet(config.BACKUP_KEY.encode())
    return None


def _purgar_antiguos():
    limite = time.time() - config.RETENCION_RESPALDOS_DIAS * 86400
    for f in glob.glob(os.path.join(config.BACKUP_DIR, "respaldo_*")):
        if os.path.getmtime(f) < limite:
            os.remove(f)


TABLAS = ["rol", "usuario", "sistema", "cultivo", "dispositivo", "sensor", "umbral", "medicion", "alerta",
          "evento_bitacora", "respaldo"]


def _volcado_json(ruta):
    import json

    with db.connect() as c, open(ruta, "w") as fh:
        datos = {t: [{k: db.iso(v) if hasattr(v, "isoformat") else v for k, v in f.items()}
                     for f in c.all(f"SELECT * FROM {t} ORDER BY id")] for t in TABLAS}
        json.dump(datos, fh)


def crear_respaldo(tipo, usuario=None):
    """Vuelca la BD (SQLite: API de backup; PostgreSQL: pg_dump) y la cifra si hay BACKUP_KEY."""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    nombre = "respaldo_" + db.utcnow().strftime("%Y%m%d_%H%M%S") + (".sql" if config.IS_PG else ".sqlite")
    ruta = os.path.join(config.BACKUP_DIR, nombre)
    estado, tam = "Completo", 0
    try:
        if config.IS_PG:
            try:
                with open(ruta, "wb") as fh:
                    subprocess.run(["pg_dump", "--no-owner", config.DATABASE_URL], stdout=fh, check=True,
                                   timeout=120, stderr=subprocess.DEVNULL)
            except Exception:
                # pg_dump ausente o de versión distinta a la del servidor: volcado lógico en JSON
                _volcado_json(ruta := ruta[:-4] + ".json")
                nombre = os.path.basename(ruta)
        else:
            src = sqlite3.connect(db.db_path_sqlite())
            dst = sqlite3.connect(ruta)
            src.backup(dst)
            dst.close()
            src.close()
        f = _fernet()
        if f:
            with open(ruta, "rb") as fh:
                datos = f.encrypt(fh.read())
            with open(ruta + ".enc", "wb") as fh:
                fh.write(datos)
            os.remove(ruta)
            ruta, nombre = ruta + ".enc", nombre + ".enc"
        tam = os.path.getsize(ruta)
        _purgar_antiguos()
    except Exception as exc:  # el fallo se registra, no se pierde
        estado = "Fallido"
        nombre = nombre + f" ({type(exc).__name__})"
    with db.connect() as c:
        rid = c.insert("respaldo", {"archivo": nombre[:200], "tamano": tam, "tipo": tipo, "estado": estado,
                                    "id_usuario": usuario["id"] if usuario else None,
                                    "creado_en": db.to_iso(db.utcnow())})
        auditar(c, usuario, "respaldo_" + tipo, f"{nombre} -> {estado}")
    return {"id": rid, "archivo": nombre, "tamano": tam, "estado": estado}


def iniciar_monitor_conexion():
    """Revisa periódicamente la conexión de los dispositivos para generar la alerta de desconexión
    aunque nadie esté mirando el dashboard."""
    if config.MONITOR_SEGUNDOS <= 0:
        return

    def bucle():
        while True:
            time.sleep(config.MONITOR_SEGUNDOS)
            try:
                with db.connect() as c:
                    estado(c)
            except Exception as exc:  # el monitor nunca debe morir por un error puntual
                print("[monitor]", type(exc).__name__, exc)

    threading.Thread(target=bucle, daemon=True, name="monitor-conexion").start()


def iniciar_respaldo_diario():
    """Hilo que dispara el respaldo automático a la hora configurada (por defecto 03:00 UTC)."""
    if not config.BACKUP_AUTO:
        return

    def bucle():
        ultimo = None
        while True:
            ahora = db.utcnow()
            clave = ahora.strftime("%Y-%m-%d")
            if ahora.strftime("%H:%M") == config.BACKUP_HORA and ultimo != clave:
                ultimo = clave
                crear_respaldo("automatico")
            time.sleep(30)

    threading.Thread(target=bucle, daemon=True, name="respaldo-diario").start()
