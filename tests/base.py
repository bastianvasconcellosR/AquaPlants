"""Infraestructura de pruebas: levanta la API real en un puerto local con una BD temporal
y ofrece un cliente HTTP mínimo. Cada caso registra esperado/obtenido para el informe."""
import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import urllib.parse
import uuid

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
JWT_SECRET = "secreto-solo-para-pruebas-0123456789"
ADMIN_EMAIL, ADMIN_PASS = "admin@aquaplants.cl", "AdminPruebas2026"
SUP = ("supervisor@aquaplants.cl", "Super2026aq")
ENC = ("encargado@aquaplants.cl", "Cultivo2026aq")
OFFLINE_S = 3

REGISTRO = []  # casos ejecutados: id, cu, descripcion, esperado, obtenido, estado


def caso(id_, cu, descripcion, esperado, obtenido, condicion):
    """Registra el caso y falla si la condición no se cumple."""
    REGISTRO.append({"id": id_, "cu": cu, "descripcion": descripcion, "esperado": esperado,
                     "obtenido": str(obtenido)[:300], "estado": "Aprobado" if condicion else "Fallido"})
    if not condicion:
        raise AssertionError(f"{id_}: esperado «{esperado}», obtenido «{obtenido}»")


def _puerto():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Servidor:
    def __init__(self, extra_env=None):
        self.dir = tempfile.mkdtemp(prefix="aq_test_")
        self.puerto = _puerto()
        self.url = f"http://127.0.0.1:{self.puerto}"
        env = {**os.environ, "DATABASE_URL": os.getenv("TEST_DATABASE_URL", f"sqlite:///{self.dir}/t.db"), "JWT_SECRET": JWT_SECRET,
               "ADMIN_PASSWORD": ADMIN_PASS, "BACKUP_DIR": f"{self.dir}/respaldos", "BACKUP_AUTO": "0",
               "OFFLINE_SEGUNDOS": str(OFFLINE_S), "MONITOR_SEGUNDOS": "1", "SEED_DEMO": "1", "APP_ENV": "test", **(extra_env or {})}
        self.log = open(f"{self.dir}/server.log", "w")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(self.puerto),
                                      "--log-level", "warning"], cwd=RAIZ, env=env, stdout=self.log, stderr=self.log)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url + "/api/v1/health", timeout=1); return
            except Exception:
                time.sleep(0.15)
        raise RuntimeError("el servidor de pruebas no arrancó:\n" + open(f"{self.dir}/server.log").read())

    def parar(self):
        self.proc.terminate()
        try: self.proc.wait(5)
        except Exception: self.proc.kill()
        self.log.close(); shutil.rmtree(self.dir, ignore_errors=True)


def http(url, metodo="GET", cuerpo=None, token=None, key=None, raw=None, headers=None):
    h = dict(headers or {})
    data = raw
    if cuerpo is not None:
        data = json.dumps(cuerpo).encode(); h["Content-Type"] = "application/json"
    if token: h["Authorization"] = "Bearer " + token
    if key: h["X-API-Key"] = key
    req = urllib.request.Request(url, data=data, method=metodo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(); cab = dict(r.headers); st = r.status
    except urllib.error.HTTPError as e:
        body = e.read(); cab = dict(e.headers); st = e.code
    try: js = json.loads(body)
    except Exception: js = None
    return st, js, body, cab


class Base(unittest.TestCase):
    srv: Servidor = None
    _tokens = {}

    @classmethod
    def setUpClass(cls):
        if Base.srv is None:
            Base.srv = Servidor()
            atexit.register(Base.srv.parar)
        cls.url = Base.srv.url + "/api/v1"

    @classmethod
    def tearDownModule(cls):
        pass

    # --- ayudas
    def api(self, metodo, ruta, cuerpo=None, token=None, key=None, **kw):
        st, js, body, cab = http(self.url + ruta, metodo, cuerpo, token, key, **kw)
        return st, js

    def login(self, email, clave):
        st, js = self.api("POST", "/auth/login", {"email": email, "clave": clave})
        return st, js

    def token(self, quien):
        email, clave = {"admin": (ADMIN_EMAIL, ADMIN_PASS), "sup": SUP, "enc": ENC}[quien]
        if quien not in Base._tokens:
            st, js = self.login(email, clave)
            assert st == 200, f"login {quien}: {st} {js}"
            Base._tokens[quien] = js["token"]
        return Base._tokens[quien]

    def entorno(self, variables=("ph", "temperatura_agua", "caudal", "conductividad_ec", "humedad_ambiente")):
        """Crea un sistema + umbrales + dispositivo aislados. Devuelve dict con ids y api_key."""
        t = self.token("admin"); suf = uuid.uuid4().hex[:8]
        st, s = self.api("POST", "/sistemas", {"nombre": f"Sis-{suf}", "ubicacion": "Prueba"}, t)
        assert st == 201, s
        defecto = {"ph": (5.5, 6.8), "temperatura_agua": (18, 26), "caudal": (0.5, 5), "conductividad_ec": (1, 2.5), "humedad_ambiente": (40, 85)}
        for v in variables:
            st, _ = self.api("POST", "/umbrales", {"id_sistema": s["id"], "variable": v, "minimo": defecto[v][0], "maximo": defecto[v][1]}, t)
            assert st == 201
        st, d = self.api("POST", "/dispositivos", {"id_sistema": s["id"], "codigo": f"T-{suf}", "nombre": "Disp prueba", "variables": list(variables)}, t)
        assert st == 201, d
        return {"sistema": s["id"], "disp": d["id"], "key": d["api_key"], "codigo": f"T-{suf}"}

    def sensor_id(self, env, variable):
        st, js = self.api("GET", "/sensores", token=self.token("admin"))
        return next(s["id"] for s in js if s["id_dispositivo"] == env["disp"] and s["variable"] == variable)

    def alertas(self, env, estado=None):
        q = "?limite=500" + (f"&estado={urllib.parse.quote(estado)}" if estado else "")
        st, js = self.api("GET", "/alertas" + q, token=self.token("admin"))
        return [a for a in js if a["dispositivo"] == env["codigo"]]
