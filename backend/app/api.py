"""Endpoints REST /api/v1. Cada ruta declara los roles que la pueden usar."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import config, db, schemas, security, services
from .security import error, requiere

routes = []
ADMIN, SUP, ENC = "Administrador", "Supervisor", "Encargado"
TODOS = (ADMIN, SUP, ENC)
P = "/api/v1"


# ---------------------------------------------------------------- infraestructura de rutas
def _adaptar(fn):
    async def endpoint(request):
        raw = await request.body()
        if len(raw) > config.MAX_BODY_BYTES:
            return error(413, "El cuerpo de la solicitud es demasiado grande")
        request.state.raw = raw
        return await run_in_threadpool(fn, request)

    return endpoint


def ruta(path, metodo, *roles, dispositivo=False, publico=False):
    def deco(fn):
        f = fn if publico else requiere(*roles, dispositivo=dispositivo)(fn)
        routes.append(Route(P + path, _adaptar(f), methods=[metodo]))
        return fn

    return deco


class _Invalido(Exception):
    def __init__(self, resp):
        self.resp = resp


def cuerpo(request, Esquema):
    try:
        datos = json.loads(request.state.raw or b"")
    except (ValueError, UnicodeDecodeError):
        raise _Invalido(error(400, "El cuerpo debe ser JSON válido"))
    try:
        return Esquema(**datos) if isinstance(datos, dict) else Esquema.model_validate(datos)
    except ValidationError as e:
        raise _Invalido(error(422, "Datos inválidos", detalles=schemas.mensajes(e)))


def manejar(fn):
    """Convierte _Invalido y violaciones de integridad en respuestas HTTP limpias."""
    import functools

    @functools.wraps(fn)
    def w(request):
        try:
            return fn(request)
        except _Invalido as e:
            return e.resp
        except services.ErrorIngesta as e:
            return error(e.status, e.mensaje)
        except Exception as e:
            if type(e).__name__ in ("IntegrityError", "UniqueViolation", "ForeignKeyViolation"):
                return error(409, "El registro duplica un dato único o referencia algo inexistente")
            raise

    return w


def ok(data, status=200):
    return JSONResponse(data, status_code=status)


def _limpiar(fila, quitar=("hash_clave", "hash_api_key")):
    out = {}
    for k, v in fila.items():
        if k in quitar:
            continue
        out[k] = db.iso(v) if isinstance(v, datetime) else v
    return out


def _fecha(txt, fin=False):
    if not txt:
        return None
    try:
        if len(txt) == 10:
            d = datetime.strptime(txt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return d + timedelta(days=1) - timedelta(seconds=1) if fin else d
        return db.parse_iso(txt)
    except ValueError:
        raise _Invalido(error(422, "Fecha inválida; use AAAA-MM-DD o AAAA-MM-DDTHH:MM:SSZ", campo=txt))


# ================================================================ sistema / salud
@ruta("/health", "GET", publico=True)
def health(request):
    try:
        with db.connect() as c:
            c.one("SELECT 1 AS ok")
        return ok({"estado": "ok", "base_de_datos": "ok", "hora": db.to_iso(db.utcnow())})
    except Exception:
        return error(503, "Base de datos no disponible")


# ================================================================ CU01 autenticación
@ruta("/auth/login", "POST", publico=True)
@manejar
def login(request):
    d = cuerpo(request, schemas.LoginIn)
    ahora = db.utcnow()
    generico = "Correo o contraseña incorrectos"
    with db.connect() as c:
        u = c.one("SELECT u.*, r.nombre AS rol FROM usuario u JOIN rol r ON r.id = u.id_rol WHERE u.email = ?",
                  (d.email.lower(),))
        if not u:
            security.verificar_clave(d.clave, "scrypt$AAAA$AAAA")  # iguala el tiempo de respuesta
            services.auditar(c, None, "login_fallido", "correo desconocido")
            return error(401, generico)
        bh = db.iso(u["bloqueado_hasta"])
        if bh and db.parse_iso(bh) > ahora:
            return error(423, "Cuenta bloqueada temporalmente por intentos fallidos. Intente más tarde.")
        if not security.verificar_clave(d.clave, u["hash_clave"]):
            n = u["intentos_fallidos"] + 1
            cambios = {"intentos_fallidos": n}
            if n >= config.MAX_INTENTOS:
                cambios = {"intentos_fallidos": 0,
                           "bloqueado_hasta": db.to_iso(ahora + timedelta(minutes=config.BLOQUEO_MINUTOS))}
            c.update("usuario", cambios, "id = ?", (u["id"],))
            services.auditar(c, u, "login_fallido", f"intento {n}")
            return error(401, generico)
        if not u["activo"]:
            return error(403, "Usuario desactivado. Contacte al Administrador.")
        c.update("usuario", {"intentos_fallidos": 0, "bloqueado_hasta": None}, "id = ?", (u["id"],))
        services.auditar(c, u, "login_ok")
    return ok({"token": security.crear_token(u, u["rol"]), "expira_en_min": config.JWT_MINUTOS,
               "usuario": {"id": u["id"], "nombre": u["nombre"], "email": u["email"], "rol": u["rol"]}})


@ruta("/auth/me", "GET")
def me(request):
    u = request.state.usuario
    return ok({"id": u["id"], "nombre": u["nombre"], "email": u["email"], "rol": u["rol"]})


# ================================================================ CU06 usuarios
def _ultimo_admin(c, uid):
    """True si uid es el único Administrador activo."""
    admins = c.all("SELECT u.id FROM usuario u JOIN rol r ON r.id = u.id_rol WHERE r.nombre = 'Administrador' AND u.activo = ?",
                   (True,))
    return len(admins) == 1 and admins[0]["id"] == uid


@ruta("/usuarios", "GET", ADMIN)
def usuarios_listar(request):
    with db.connect() as c:
        filas = c.all("SELECT u.id, u.nombre, u.email, u.activo, r.nombre AS rol, u.creado_en "
                      "FROM usuario u JOIN rol r ON r.id = u.id_rol ORDER BY u.id")
    return ok([_limpiar(f) for f in filas])


@ruta("/usuarios", "POST", ADMIN)
@manejar
def usuarios_crear(request):
    d = cuerpo(request, schemas.UsuarioIn)
    if not d.clave:
        return error(422, "Datos inválidos", detalles=[{"campo": "clave", "mensaje": "la contraseña es obligatoria"}])
    falla = security.validar_politica(d.clave)
    if falla:
        return error(422, "Datos inválidos", detalles=[{"campo": "clave", "mensaje": falla}])
    with db.connect() as c:
        if c.one("SELECT id FROM usuario WHERE email = ?", (d.email,)):
            return error(409, "Ya existe un usuario con ese correo")
        rol = c.one("SELECT id FROM rol WHERE nombre = ?", (d.rol,))
        uid = c.insert("usuario", {"nombre": d.nombre, "email": d.email, "hash_clave": security.hash_clave(d.clave),
                                   "id_rol": rol["id"], "activo": d.activo, "intentos_fallidos": 0,
                                   "creado_en": db.to_iso(db.utcnow())})
        services.auditar(c, request.state.usuario, "usuario_creado", f"id={uid} rol={d.rol}")
    return ok({"id": uid}, 201)


@ruta("/usuarios/{id:int}", "PUT", ADMIN)
@manejar
def usuarios_editar(request):
    uid = request.path_params["id"]
    d = cuerpo(request, schemas.UsuarioIn)
    with db.connect() as c:
        u = c.one("SELECT u.*, r.nombre AS rol FROM usuario u JOIN rol r ON r.id = u.id_rol WHERE u.id = ?", (uid,))
        if not u:
            return error(404, "Usuario no encontrado")
        if (not d.activo or d.rol != ADMIN) and u["rol"] == ADMIN and _ultimo_admin(c, uid):
            return error(409, "No se puede desactivar ni degradar al último Administrador activo")
        if c.one("SELECT id FROM usuario WHERE email = ? AND id <> ?", (d.email, uid)):
            return error(409, "Ya existe un usuario con ese correo")
        cambios = {"nombre": d.nombre, "email": d.email, "activo": d.activo,
                   "id_rol": c.one("SELECT id FROM rol WHERE nombre = ?", (d.rol,))["id"]}
        if d.clave:
            falla = security.validar_politica(d.clave)
            if falla:
                return error(422, "Datos inválidos", detalles=[{"campo": "clave", "mensaje": falla}])
            cambios["hash_clave"] = security.hash_clave(d.clave)
        c.update("usuario", cambios, "id = ?", (uid,))
        services.auditar(c, request.state.usuario, "usuario_editado", f"id={uid}")
    return ok({"id": uid})


@ruta("/usuarios/{id:int}", "DELETE", ADMIN)
def usuarios_desactivar(request):
    uid = request.path_params["id"]
    with db.connect() as c:
        u = c.one("SELECT u.*, r.nombre AS rol FROM usuario u JOIN rol r ON r.id = u.id_rol WHERE u.id = ?", (uid,))
        if not u:
            return error(404, "Usuario no encontrado")
        if u["rol"] == ADMIN and _ultimo_admin(c, uid):
            return error(409, "No se puede desactivar al último Administrador activo")
        c.update("usuario", {"activo": False}, "id = ?", (uid,))
        services.auditar(c, request.state.usuario, "usuario_desactivado", f"id={uid}")
    return ok({"id": uid, "activo": False})


@ruta("/roles", "GET", ADMIN)
def roles(request):
    with db.connect() as c:
        return ok(c.all("SELECT id, nombre FROM rol ORDER BY id"))


# ================================================================ CU07 sistemas / cultivos / dispositivos / sensores
def _existe(c, tabla, id_):
    return c.one(f"SELECT id FROM {tabla} WHERE id = ?", (id_,)) is not None


def _crud(nombre, tabla, Esquema, campos, fk=None):
    """Registra GET lista / GET uno / POST / PUT / DELETE(desactivar) para una entidad simple."""

    @ruta(f"/{nombre}", "GET", *TODOS)
    def listar(request, _t=tabla):
        with db.connect() as c:
            return ok([_limpiar(f) for f in c.all(f"SELECT * FROM {_t} ORDER BY id")])

    @ruta(f"/{nombre}/{{id:int}}", "GET", *TODOS)
    def uno(request, _t=tabla):
        with db.connect() as c:
            f = c.one(f"SELECT * FROM {_t} WHERE id = ?", (request.path_params["id"],))
        return ok(_limpiar(f)) if f else error(404, "No encontrado")

    @ruta(f"/{nombre}", "POST", ADMIN)
    @manejar
    def crear(request, _t=tabla):
        d = cuerpo(request, Esquema)
        with db.connect() as c:
            if fk and not _existe(c, fk[1], getattr(d, fk[0])):
                return error(422, "Datos inválidos", detalles=[{"campo": fk[0], "mensaje": "referencia inexistente"}])
            nuevo = c.insert(_t, {k: getattr(d, k) for k in campos})
            services.auditar(c, request.state.usuario, f"{_t}_creado", f"id={nuevo}")
        return ok({"id": nuevo}, 201)

    @ruta(f"/{nombre}/{{id:int}}", "PUT", ADMIN)
    @manejar
    def editar(request, _t=tabla):
        i = request.path_params["id"]
        d = cuerpo(request, Esquema)
        with db.connect() as c:
            if not _existe(c, _t, i):
                return error(404, "No encontrado")
            if fk and not _existe(c, fk[1], getattr(d, fk[0])):
                return error(422, "Datos inválidos", detalles=[{"campo": fk[0], "mensaje": "referencia inexistente"}])
            c.update(_t, {k: getattr(d, k) for k in campos}, "id = ?", (i,))
            services.auditar(c, request.state.usuario, f"{_t}_editado", f"id={i}")
        return ok({"id": i})

    @ruta(f"/{nombre}/{{id:int}}", "DELETE", ADMIN)
    def desactivar(request, _t=tabla):
        i = request.path_params["id"]
        with db.connect() as c:
            if not _existe(c, _t, i):
                return error(404, "No encontrado")
            c.update(_t, {"activo": False}, "id = ?", (i,))
            services.auditar(c, request.state.usuario, f"{_t}_desactivado", f"id={i}")
        return ok({"id": i, "activo": False})


_crud("sistemas", "sistema", schemas.SistemaIn, ["nombre", "ubicacion", "activo"])
_crud("cultivos", "cultivo", schemas.CultivoIn, ["id_sistema", "nombre", "especie", "fecha_inicio", "activo"],
      fk=("id_sistema", "sistema"))
_crud("sensores", "sensor", schemas.SensorIn, ["id_dispositivo", "variable", "unidad", "activo"],
      fk=("id_dispositivo", "dispositivo"))


@ruta("/dispositivos", "GET", *TODOS)
def disp_listar(request):
    with db.connect() as c:
        return ok([_limpiar(f) for f in c.all("SELECT * FROM dispositivo ORDER BY id")])


@ruta("/dispositivos", "POST", ADMIN)
@manejar
def disp_crear(request):
    d = cuerpo(request, schemas.DispositivoIn)
    with db.connect() as c:
        if not _existe(c, "sistema", d.id_sistema):
            return error(422, "Datos inválidos", detalles=[{"campo": "id_sistema", "mensaje": "referencia inexistente"}])
        if c.one("SELECT id FROM dispositivo WHERE codigo = ?", (d.codigo,)):
            return error(409, "Ya existe un dispositivo con ese código")
        did = c.insert("dispositivo", {"id_sistema": d.id_sistema, "codigo": d.codigo, "nombre": d.nombre,
                                       "tipo": d.tipo, "hash_api_key": "pendiente", "activo": d.activo})
        key = security.generar_api_key(did)
        c.update("dispositivo", {"hash_api_key": security.hash_api_key(key)}, "id = ?", (did,))
        for v in d.variables or []:
            c.insert("sensor", {"id_dispositivo": did, "variable": v, "unidad": config.UNIDADES[v], "activo": True})
        services.auditar(c, request.state.usuario, "dispositivo_creado", f"id={did} codigo={d.codigo}")
    return ok({"id": did, "api_key": key,
               "aviso": "Guarde la API Key: no se volverá a mostrar."}, 201)


@ruta("/dispositivos/{id:int}", "PUT", ADMIN)
@manejar
def disp_editar(request):
    i = request.path_params["id"]
    d = cuerpo(request, schemas.DispositivoIn)
    with db.connect() as c:
        if not _existe(c, "dispositivo", i):
            return error(404, "No encontrado")
        if c.one("SELECT id FROM dispositivo WHERE codigo = ? AND id <> ?", (d.codigo, i)):
            return error(409, "Ya existe un dispositivo con ese código")
        c.update("dispositivo", {"id_sistema": d.id_sistema, "codigo": d.codigo, "nombre": d.nombre,
                                 "tipo": d.tipo, "activo": d.activo}, "id = ?", (i,))
        services.auditar(c, request.state.usuario, "dispositivo_editado", f"id={i}")
    return ok({"id": i})


@ruta("/dispositivos/{id:int}", "DELETE", ADMIN)
def disp_desactivar(request):
    i = request.path_params["id"]
    with db.connect() as c:
        if not _existe(c, "dispositivo", i):
            return error(404, "No encontrado")
        c.update("dispositivo", {"activo": False}, "id = ?", (i,))
        services.auditar(c, request.state.usuario, "dispositivo_desactivado", f"id={i}")
    return ok({"id": i, "activo": False})


@ruta("/dispositivos/{id:int}/regenerar-clave", "POST", ADMIN)
def disp_regenerar(request):
    i = request.path_params["id"]
    with db.connect() as c:
        if not _existe(c, "dispositivo", i):
            return error(404, "No encontrado")
        key = security.generar_api_key(i)
        c.update("dispositivo", {"hash_api_key": security.hash_api_key(key)}, "id = ?", (i,))
        services.auditar(c, request.state.usuario, "dispositivo_clave_regenerada", f"id={i}")
    return ok({"id": i, "api_key": key, "aviso": "La clave anterior quedó revocada. Guarde esta: no se volverá a mostrar."})


# ================================================================ CU08 umbrales
@ruta("/umbrales", "GET", *TODOS)
def umbrales_listar(request):
    with db.connect() as c:
        return ok(c.all("SELECT * FROM umbral ORDER BY id_sistema, variable"))


@ruta("/umbrales", "POST", ADMIN)
@manejar
def umbrales_crear(request):
    d = cuerpo(request, schemas.UmbralIn)
    with db.connect() as c:
        if not _existe(c, "sistema", d.id_sistema):
            return error(422, "Datos inválidos", detalles=[{"campo": "id_sistema", "mensaje": "referencia inexistente"}])
        if c.one("SELECT id FROM umbral WHERE id_sistema = ? AND variable = ?", (d.id_sistema, d.variable)):
            return error(409, "Ya existe un umbral para esa variable en el sistema; edítelo")
        i = c.insert("umbral", {"id_sistema": d.id_sistema, "variable": d.variable, "minimo": d.minimo, "maximo": d.maximo})
        services.auditar(c, request.state.usuario, "umbral_creado", f"{d.variable} {d.minimo}-{d.maximo}")
    return ok({"id": i}, 201)


@ruta("/umbrales/{id:int}", "PUT", ADMIN)
@manejar
def umbrales_editar(request):
    i = request.path_params["id"]
    d = cuerpo(request, schemas.UmbralIn)
    with db.connect() as c:
        if not _existe(c, "umbral", i):
            return error(404, "No encontrado")
        c.update("umbral", {"minimo": d.minimo, "maximo": d.maximo}, "id = ?", (i,))
        services.auditar(c, request.state.usuario, "umbral_modificado", f"id={i} {d.variable} {d.minimo}-{d.maximo}")
    return ok({"id": i})


# ================================================================ CU09 / CU10 ingesta
@ruta("/mediciones", "POST", dispositivo=True)
@manejar
def medicion_recibir(request):
    m = cuerpo(request, schemas.MedicionIn)
    with db.connect() as c:
        r = services.recibir(c, request.state.dispositivo, m)
    return ok(r, 201)


@ruta("/mediciones/lote", "POST", dispositivo=True)
@manejar
def medicion_lote(request):
    lote = cuerpo(request, schemas.LoteIn)
    with db.connect() as c:
        r = services.recibir_lote(c, request.state.dispositivo, lote)
    return ok(r, 201)


# ================================================================ CU02 dashboard
@ruta("/dashboard/estado", "GET", *TODOS)
def dashboard(request):
    with db.connect() as c:
        return ok(services.estado(c))


# ================================================================ CU03 / CU04 alertas
@ruta("/alertas", "GET", *TODOS)
def alertas_listar(request):
    estado = request.query_params.get("estado")
    if estado and estado not in services.ESTADOS_ALERTA:
        return error(422, "Estado inválido", validos=list(services.ESTADOS_ALERTA))
    try:
        limite = max(1, min(int(request.query_params.get("limite", "100")), 500))
    except ValueError:
        return error(422, "limite debe ser un entero")
    sql = """SELECT a.id, a.tipo, a.severidad, a.mensaje, a.valor, a.estado, a.causa, a.creada_en, a.actualizada_en,
                    d.codigo AS dispositivo, d.id_sistema, s.variable
             FROM alerta a JOIN dispositivo d ON d.id = a.id_dispositivo LEFT JOIN sensor s ON s.id = a.id_sensor"""
    params = []
    if estado:
        sql += " WHERE a.estado = ?"
        params.append(estado)
    sql += " ORDER BY a.creada_en DESC, a.id DESC LIMIT ?"
    params.append(limite)
    with db.connect() as c:
        filas = c.all(sql, params)
        cult = services.cultivos_por_sistema(c)
    salida = []
    for f in filas:
        f = _limpiar(f)
        f["cultivos"] = cult.get(f.pop("id_sistema", None), [])   # cultivos del sistema donde está el dispositivo
        salida.append(f)
    return ok(salida)


@ruta("/alertas/{id:int}", "PATCH", *TODOS)
@manejar
def alerta_gestionar(request):
    i = request.path_params["id"]
    d = cuerpo(request, schemas.AlertaPatch)
    with db.connect() as c:
        a = c.one("SELECT * FROM alerta WHERE id = ?", (i,))
        if not a:
            return error(404, "Alerta no encontrada")
        if a["estado"] == "Resuelta":
            return error(409, "La alerta ya está resuelta y no admite cambios")
        if a["estado"] == d.estado:
            return error(409, f"La alerta ya está '{d.estado}'")
        if d.estado == "Resuelta" and not (d.causa and d.causa.strip()):
            return error(422, "Datos inválidos", detalles=[{"campo": "causa", "mensaje": "la causa o solución es obligatoria al resolver"}])
        c.update("alerta", {"estado": d.estado, "causa": (d.causa or a["causa"]), "actualizada_en": db.to_iso(db.utcnow()),
                            "id_usuario": request.state.usuario["id"]}, "id = ?", (i,))
        services.auditar(c, request.state.usuario, "alerta_" + d.estado.lower().replace(" ", "_"), f"id={i}")
    return ok({"id": i, "estado": d.estado})


# ================================================================ CU05 histórico / CU12 CSV
def _filtro_hist(request):
    q = request.query_params
    sid = q.get("id_sensor")
    if sid is not None and not sid.isdigit():
        raise _Invalido(error(422, "id_sensor debe ser un entero"))
    hasta = _fecha(q.get("hasta"), fin=True) or db.utcnow()
    desde = _fecha(q.get("desde")) or (hasta - timedelta(hours=24))
    if desde > hasta:
        raise _Invalido(error(422, "'desde' no puede ser posterior a 'hasta'"))
    if hasta - desde > timedelta(days=366):
        raise _Invalido(error(422, "El rango máximo de consulta es de un año"))
    return (int(sid) if sid else None), db.to_iso(desde), db.to_iso(hasta)


@ruta("/historico", "GET", *TODOS)
@manejar
def historico(request):
    sid, desde, hasta = _filtro_hist(request)
    if sid is None:
        return error(422, "id_sensor es obligatorio")
    try:
        maxp = max(10, min(int(request.query_params.get("max_puntos", "600")), 5000))
    except ValueError:
        return error(422, "max_puntos debe ser un entero")
    with db.connect() as c:
        sen = c.one("SELECT se.id, se.variable, se.unidad, d.codigo FROM sensor se JOIN dispositivo d ON d.id = se.id_dispositivo WHERE se.id = ?", (sid,))
        if not sen:
            return error(404, "Sensor no encontrado")
        r = c.one("SELECT COUNT(*) AS n, MIN(valor) AS mn, MAX(valor) AS mx, AVG(valor) AS prom FROM medicion "
                  "WHERE id_sensor = ? AND marca_tiempo >= ? AND marca_tiempo <= ?", (sid, desde, hasta))
        filas = c.all("SELECT marca_tiempo, valor FROM medicion WHERE id_sensor = ? AND marca_tiempo >= ? "
                      "AND marca_tiempo <= ? ORDER BY marca_tiempo LIMIT 50000", (sid, desde, hasta))
    paso = max(1, -(-len(filas) // maxp))
    pts = [{"t": db.iso(f["marca_tiempo"]), "v": f["valor"]} for f in filas[::paso]]
    return ok({"sensor": dict(sen), "desde": desde, "hasta": hasta, "total": r["n"],
               "minimo": r["mn"], "maximo": r["mx"], "promedio": round(r["prom"], 3) if r["prom"] is not None else None,
               "puntos": pts})


@ruta("/historico/export.csv", "GET", ADMIN, SUP)
@manejar
def exportar(request):
    sid, desde, hasta = _filtro_hist(request)
    sql = ("SELECT m.marca_tiempo, d.codigo, se.variable, m.valor, se.unidad FROM medicion m "
           "JOIN sensor se ON se.id = m.id_sensor JOIN dispositivo d ON d.id = se.id_dispositivo "
           "WHERE m.marca_tiempo >= ? AND m.marca_tiempo <= ?")
    params = [desde, hasta]
    if sid:
        sql += " AND m.id_sensor = ?"
        params.append(sid)
    sql += " ORDER BY m.marca_tiempo LIMIT ?"
    with db.connect() as c:
        filas = c.all(sql, params + [config.MAX_EXPORT_FILAS + 1])
        if len(filas) > config.MAX_EXPORT_FILAS:
            return error(422, f"La consulta supera {config.MAX_EXPORT_FILAS} filas; acote el rango o el sensor")
        services.auditar(c, request.state.usuario, "exportacion_csv", f"{len(filas)} filas {desde}..{hasta}")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["marca_tiempo", "dispositivo", "variable", "valor", "unidad"])
    for f in filas:
        w.writerow([db.iso(f["marca_tiempo"]), f["codigo"], f["variable"], f["valor"], f["unidad"]])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="historico_aquaplants.csv"'})


# ================================================================ Informe de gestión
@ruta("/informes/gestion", "GET", ADMIN, SUP)
@manejar
def informe_gestion(request):
    """Resumen ejecutivo del período: operación, calidad de datos, alertas y desempeño por dispositivo."""
    _, desde, hasta = _filtro_hist(request)
    with db.connect() as c:
        disp = c.all("SELECT d.id, d.codigo, d.nombre, d.ultima_comunicacion, d.id_sistema, s.nombre AS sistema "
                     "FROM dispositivo d JOIN sistema s ON s.id = d.id_sistema WHERE d.activo = ? ORDER BY d.id", (True,))
        limite = db.utcnow() - timedelta(seconds=config.OFFLINE_SEGUNDOS)
        en_linea = sum(1 for d in disp if d["ultima_comunicacion"] and db.parse_iso(db.iso(d["ultima_comunicacion"])) >= limite)
        n_sensores = c.one("SELECT COUNT(*) AS n FROM sensor WHERE activo = ?", (True,))["n"]
        por_var = c.all(
            "SELECT se.variable, se.unidad, COUNT(m.id) AS n, MIN(m.valor) AS mn, MAX(m.valor) AS mx, AVG(m.valor) AS prom, "
            "SUM(CASE WHEN u.id IS NOT NULL AND (m.valor < u.minimo OR m.valor > u.maximo) THEN 1 ELSE 0 END) AS fuera, "
            "MAX(u.minimo) AS umin, MAX(u.maximo) AS umax "
            "FROM sensor se JOIN dispositivo d ON d.id = se.id_dispositivo "
            "JOIN medicion m ON m.id_sensor = se.id AND m.marca_tiempo >= ? AND m.marca_tiempo <= ? "
            "LEFT JOIN umbral u ON u.id_sistema = d.id_sistema AND u.variable = se.variable "
            "GROUP BY se.variable, se.unidad ORDER BY se.variable", (desde, hasta))
        por_disp = c.all(
            "SELECT d.codigo, COUNT(m.id) AS n FROM dispositivo d JOIN sensor se ON se.id_dispositivo = d.id "
            "LEFT JOIN medicion m ON m.id_sensor = se.id AND m.marca_tiempo >= ? AND m.marca_tiempo <= ? "
            "WHERE d.activo = ? GROUP BY d.codigo ORDER BY d.codigo", (desde, hasta, True))
        alertas = c.all(
            "SELECT a.id, a.tipo, a.severidad, a.mensaje, a.estado, a.causa, a.creada_en, a.actualizada_en, d.codigo AS dispositivo "
            "FROM alerta a JOIN dispositivo d ON d.id = a.id_dispositivo WHERE a.creada_en >= ? AND a.creada_en <= ? "
            "ORDER BY a.creada_en DESC, a.id DESC", (desde, hasta))
        abiertas = c.one("SELECT COUNT(*) AS n FROM alerta WHERE estado <> 'Resuelta'")["n"]
        eventos = c.one("SELECT COUNT(*) AS n FROM evento_bitacora WHERE categoria = 'agricola' AND creado_en >= ? AND creado_en <= ?", (desde, hasta))["n"]
        cultivos = c.all("SELECT cu.id, cu.nombre, cu.especie, cu.fecha_inicio, cu.id_sistema, s.nombre AS sistema "
                         "FROM cultivo cu JOIN sistema s ON s.id = cu.id_sistema WHERE cu.activo = ? ORDER BY cu.id", (True,))
        med_sis = {f["id_sistema"]: f["n"] for f in c.all(
            "SELECT d.id_sistema, COUNT(m.id) AS n FROM dispositivo d JOIN sensor se ON se.id_dispositivo = d.id "
            "JOIN medicion m ON m.id_sensor = se.id AND m.marca_tiempo >= ? AND m.marca_tiempo <= ? "
            "GROUP BY d.id_sistema", (desde, hasta))}
        ale_sis = {f["id_sistema"]: f for f in c.all(
            "SELECT d.id_sistema, COUNT(a.id) AS n, SUM(CASE WHEN a.estado <> 'Resuelta' THEN 1 ELSE 0 END) AS abiertas "
            "FROM alerta a JOIN dispositivo d ON d.id = a.id_dispositivo "
            "WHERE a.creada_en >= ? AND a.creada_en <= ? GROUP BY d.id_sistema", (desde, hasta))}
        bit_cul = {f["id_cultivo"]: f["n"] for f in c.all(
            "SELECT id_cultivo, COUNT(*) AS n FROM evento_bitacora WHERE categoria = 'agricola' AND id_cultivo IS NOT NULL "
            "AND creado_en >= ? AND creado_en <= ? GROUP BY id_cultivo", (desde, hasta))}
        services.auditar(c, request.state.usuario, "informe_gestion", f"{desde}..{hasta}")
    tiempos = []
    for a in alertas:
        if a["estado"] == "Resuelta" and a["actualizada_en"]:
            t = (db.parse_iso(db.iso(a["actualizada_en"])) - db.parse_iso(db.iso(a["creada_en"]))).total_seconds() / 60
            tiempos.append(max(t, 0))
    cuenta = lambda k, v: sum(1 for a in alertas if a[k] == v)
    total_med = sum(v["n"] for v in por_var)
    total_fuera = sum(v["fuera"] or 0 for v in por_var)
    variables = []
    for v in por_var:
        variables.append({"variable": v["variable"], "unidad": v["unidad"], "mediciones": v["n"], "minimo": v["mn"], "maximo": v["mx"],
                          "promedio": round(v["prom"], 2) if v["prom"] is not None else None,
                          "fuera_de_rango": int(v["fuera"] or 0),
                          "pct_fuera": round(100.0 * (v["fuera"] or 0) / v["n"], 1) if v["n"] else 0.0,
                          "umbral_min": v["umin"], "umbral_max": v["umax"]})
    return ok({
        "desde": desde, "hasta": hasta, "generado_en": db.to_iso(db.utcnow()), "generado_por": request.state.usuario["nombre"],
        "resumen": {"dispositivos_activos": len(disp), "dispositivos_en_linea": en_linea, "sensores_activos": n_sensores,
                    "mediciones": total_med, "mediciones_fuera_de_rango": int(total_fuera),
                    "pct_fuera_de_rango": round(100.0 * total_fuera / total_med, 1) if total_med else 0.0,
                    "alertas_periodo": len(alertas), "alertas_criticas": cuenta("severidad", "Crítica"),
                    "alertas_por_umbral": cuenta("tipo", "umbral"), "alertas_desconexion": cuenta("tipo", "desconexion"),
                    "alertas_resueltas": len(tiempos), "alertas_abiertas_ahora": abiertas,
                    "tiempo_medio_resolucion_min": round(sum(tiempos) / len(tiempos), 1) if tiempos else None,
                    "registros_bitacora_agricola": eventos},
        "por_variable": variables,
        "por_dispositivo": [{"dispositivo": d["codigo"], "mediciones": d["n"]} for d in por_disp],
        "dispositivos": [{"codigo": d["codigo"], "nombre": d["nombre"], "sistema": d["sistema"], "ultima_comunicacion": db.iso(d["ultima_comunicacion"])} for d in disp],
        "alertas": [_limpiar(a) for a in alertas[:30]],
        "por_cultivo": [{"cultivo": cu["nombre"], "especie": cu["especie"], "sistema": cu["sistema"],
                         "dispositivos": sum(1 for d in disp if d["id_sistema"] == cu["id_sistema"]),
                         "mediciones": int(med_sis.get(cu["id_sistema"], 0)),
                         "alertas": int((ale_sis.get(cu["id_sistema"]) or {}).get("n") or 0),
                         "alertas_abiertas": int((ale_sis.get(cu["id_sistema"]) or {}).get("abiertas") or 0),
                         "registros_bitacora": int(bit_cul.get(cu["id"], 0))} for cu in cultivos],
    })


# ================================================================ CU11 bitácora / auditoría
@ruta("/bitacora", "GET", *TODOS)
def bitacora_listar(request):
    cat = request.query_params.get("categoria", "agricola")
    if cat not in ("agricola", "auditoria"):
        return error(422, "categoria debe ser 'agricola' o 'auditoria'")
    if cat == "auditoria" and request.state.usuario["rol"] != ADMIN:
        return error(403, "Solo el Administrador puede ver los registros de auditoría")
    with db.connect() as c:
        filas = c.all("""SELECT b.id, b.categoria, b.accion, b.detalle, b.creado_en, b.id_cultivo,
                                u.nombre AS usuario, cu.nombre AS cultivo
                         FROM evento_bitacora b LEFT JOIN usuario u ON u.id = b.id_usuario
                         LEFT JOIN cultivo cu ON cu.id = b.id_cultivo
                         WHERE b.categoria = ? ORDER BY b.creado_en DESC, b.id DESC LIMIT 200""", (cat,))
    return ok([_limpiar(f) for f in filas])


@ruta("/bitacora", "POST", ENC)
@manejar
def bitacora_crear(request):
    d = cuerpo(request, schemas.BitacoraIn)
    with db.connect() as c:
        cu = c.one("SELECT id, activo FROM cultivo WHERE id = ?", (d.id_cultivo,))
        if not cu:
            return error(422, "Datos inválidos", detalles=[{"campo": "id_cultivo", "mensaje": "cultivo inexistente"}])
        if not cu["activo"]:
            return error(409, "El cultivo está desactivado")
        i = c.insert("evento_bitacora", {"categoria": "agricola", "id_usuario": request.state.usuario["id"],
                                         "id_cultivo": d.id_cultivo, "accion": d.accion, "detalle": d.detalle,
                                         "creado_en": db.to_iso(db.utcnow())})
    return ok({"id": i}, 201)


# ================================================================ CU13 respaldos
@ruta("/respaldos", "GET", ADMIN)
def respaldos_listar(request):
    with db.connect() as c:
        return ok([_limpiar(f) for f in c.all("SELECT * FROM respaldo ORDER BY id DESC LIMIT 50")])


@ruta("/respaldos", "POST", ADMIN)
def respaldos_crear(request):
    r = services.crear_respaldo("manual", request.state.usuario)
    return ok(r, 201 if r["estado"] == "Completo" else 500)
