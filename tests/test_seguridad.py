"""Pruebas de seguridad (PS): autenticación, autorización por rol, inyección, cabeceras y abuso."""
import base64
import json
import sqlite3
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from tests.base import ADMIN_PASS, JWT_SECRET, Base, Servidor, caso, http

PROTEGIDOS = [("GET", "/dashboard/estado"), ("GET", "/alertas"), ("GET", "/historico?id_sensor=1"), ("GET", "/bitacora"),
              ("GET", "/usuarios"), ("GET", "/sistemas"), ("GET", "/cultivos"), ("GET", "/dispositivos"), ("GET", "/sensores"),
              ("GET", "/umbrales"), ("GET", "/respaldos"), ("POST", "/respaldos"), ("GET", "/historico/export.csv"),
              ("PATCH", "/alertas/1"), ("POST", "/sistemas"), ("DELETE", "/usuarios/1")]


class Seguridad(Base):
    def test_ps01_sin_token(self):
        res = {f"{m} {r}": self.api(m, r, {} if m in ("POST", "PATCH") else None)[0] for m, r in PROTEGIDOS}
        mal = {k: v for k, v in res.items() if v != 401}
        caso("PS-01", "CU01", f"{len(PROTEGIDOS)} endpoints protegidos sin token", "todos responden 401", "todos 401" if not mal else mal, not mal)

    def test_ps02_matriz_roles(self):
        enc, sup, adm = self.token("enc"), self.token("sup"), self.token("admin")
        e = self.entorno()
        pruebas = [  # (descripción, status obtenido, esperado)
            ("Encargado GET /usuarios", self.api("GET", "/usuarios", token=enc)[0], 403),
            ("Supervisor GET /usuarios", self.api("GET", "/usuarios", token=sup)[0], 403),
            ("Encargado GET /respaldos", self.api("GET", "/respaldos", token=enc)[0], 403),
            ("Encargado exportar CSV", self.api("GET", "/historico/export.csv?id_sensor=1", token=enc)[0], 403),
            ("Supervisor crear sistema", self.api("POST", "/sistemas", {"nombre": "x"}, sup)[0], 403),
            ("Encargado crear sistema", self.api("POST", "/sistemas", {"nombre": "x"}, enc)[0], 403),
            ("Supervisor editar umbral", self.api("PUT", "/umbrales/1", {"id_sistema": 1, "variable": "ph", "minimo": 5, "maximo": 7}, sup)[0], 403),
            ("Encargado desactivar dispositivo", self.api("DELETE", f"/dispositivos/{e['disp']}", token=enc)[0], 403),
            ("Supervisor regenerar clave", self.api("POST", f"/dispositivos/{e['disp']}/regenerar-clave", token=sup)[0], 403),
            ("Administrador envía medición con JWT (solo dispositivos)", self.api("POST", "/mediciones", {"variable": "ph", "valor": 6}, token=adm)[0], 401),
            ("Usuario con clave de dispositivo en cabecera Authorization", self.api("POST", "/mediciones", {"variable": "ph", "valor": 6}, token=e["key"])[0], 401),
            ("Dispositivo usa su API Key en endpoint de usuario", self.api("GET", "/dashboard/estado", key=e["key"])[0], 401),
            ("Supervisor puede gestionar alertas", self.api("PATCH", "/alertas/99999999", {"estado": "En proceso"}, sup)[0], 404),
            ("Supervisor puede leer sistemas", self.api("GET", "/sistemas", token=sup)[0], 200),
        ]
        mal = [(d, o, x) for d, o, x in pruebas if o != x]
        caso("PS-02", "CU06", "Matriz de autorización por rol (la validación ocurre en el backend)",
             f"{len(pruebas)} combinaciones rol/endpoint con el resultado de la matriz de la ES2", "todas coinciden" if not mal else mal, not mal)

    def test_ps03_bloqueo_por_intentos(self):
        t = self.token("admin"); mail = f"bloq{uuid.uuid4().hex[:6]}@aquaplants.cl"
        self.api("POST", "/usuarios", {"nombre": "Bloqueo", "email": mail, "clave": "ClaveBuena2026", "rol": "Encargado"}, t)
        codigos = [self.login(mail, "mala-clave-1")[0] for _ in range(5)]
        correcta, js = self.login(mail, "ClaveBuena2026")
        caso("PS-03", "CU01", "Bloqueo tras 5 intentos fallidos consecutivos", "5 × 401; luego incluso la clave correcta responde 423",
             f"{codigos} → clave correcta: {correcta}", codigos == [401] * 5 and correcta == 423)

    def test_ps04_intentos_se_reinician(self):
        t = self.token("admin"); mail = f"reini{uuid.uuid4().hex[:6]}@aquaplants.cl"
        self.api("POST", "/usuarios", {"nombre": "Reinicio", "email": mail, "clave": "ClaveBuena2026", "rol": "Encargado"}, t)
        for _ in range(4):
            self.login(mail, "mala-clave-1")
        ok, _ = self.login(mail, "ClaveBuena2026")
        for _ in range(4):
            self.login(mail, "mala-clave-1")
        ok2, _ = self.login(mail, "ClaveBuena2026")
        caso("PS-04", "CU01", "Un login correcto reinicia el contador de intentos", "4 fallos + éxito + 4 fallos + éxito → ambos 200 (no hay bloqueo)", f"{ok}, {ok2}", ok == 200 and ok2 == 200)

    def test_ps05_inyeccion_sql(self):
        payloads = ["' OR '1'='1", "admin@aquaplants.cl' --", "'; DROP TABLE usuario; --", "\" OR \"\"=\""]
        logins = [self.login(p, p)[0] for p in payloads]
        e = self.entorno(); t = self.token("enc")
        q = [self.api("GET", f"/alertas?estado={urllib.parse.quote(p)}", token=t)[0] for p in ("' OR 1=1 --", "Pendiente'; DROP TABLE alerta;--")]
        h = [self.api("GET", f"/historico?id_sensor={urllib.parse.quote(p)}", token=t)[0] for p in ("1 OR 1=1", "1; DROP TABLE medicion")]
        b = self.api("POST", "/bitacora", {"id_cultivo": 1, "accion": "x'); DROP TABLE evento_bitacora;--", "detalle": "' OR '1'='1"}, t)[0]
        despues = self.login("encargado@aquaplants.cl", "Cultivo2026aq")[0]
        caso("PS-05", "CU09", "Inyección SQL en login, filtros, parámetros y cuerpo",
             "ninguna da acceso ni error 500; las tablas siguen existiendo y el login normal funciona",
             f"login {logins}; alertas {q}; histórico {h}; bitácora {b}; login posterior {despues}",
             all(x in (401, 422) for x in logins) and all(x == 422 for x in q) and all(x == 422 for x in h) and b == 201 and despues == 200)

    def test_ps06_jwt_manipulado(self):
        ahora = datetime.now(timezone.utc)
        base = {"sub": "1", "rol": "Administrador", "iat": int(ahora.timestamp()), "exp": int((ahora + timedelta(hours=1)).timestamp())}
        firma_ajena = jwt.encode(base, "otro-secreto-cualquiera-0123456789abc", algorithm="HS256")
        sin_alg = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode() + "." + \
            base64.urlsafe_b64encode(json.dumps(base).encode()).rstrip(b"=").decode() + "."
        tok = self.token("enc")
        h, p, s = tok.split(".")
        pl = json.loads(base64.urlsafe_b64decode(p + "=="))
        pl["rol"] = "Administrador"
        escalado = h + "." + base64.urlsafe_b64encode(json.dumps(pl).encode()).rstrip(b"=").decode() + "." + s
        r = [self.api("GET", "/usuarios", token=t)[0] for t in (firma_ajena, sin_alg, escalado, "basura")]
        caso("PS-06", "CU01", "JWT con firma ajena, algoritmo 'none', rol alterado y basura", "los 4 responden 401", f"{r}", r == [401] * 4)

    def test_ps07_cabeceras(self):
        _, _, _, cab = http(self.url + "/health")
        cab = {k.lower(): v for k, v in cab.items()}
        _, _, _, cab_api = http(self.url + "/dashboard/estado")
        falta = [h for h in ("x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy") if h not in cab]
        caso("PS-07", "—", "Cabeceras de seguridad HTTP y sin caché en la API", "nosniff, DENY, CSP, referrer-policy; cache-control: no-store",
             f"faltan={falta}; cache-control={cab.get('cache-control')}", not falta and cab["x-frame-options"] == "DENY" and cab.get("cache-control") == "no-store")

    def test_ps08_secretos_no_expuestos(self):
        t = self.token("admin"); e = self.entorno()
        _, us = self.api("GET", "/usuarios", token=t); _, ds = self.api("GET", "/dispositivos", token=t)
        fuga = [k for r in us + ds for k in r if "hash" in k or "clave" in k or "key" in k]
        bd = sqlite3.connect(Base.srv.dir + "/t.db")
        hashes = [r[0] for r in bd.execute("SELECT hash_clave FROM usuario")]
        keys = [r[0] for r in bd.execute("SELECT hash_api_key FROM dispositivo WHERE codigo = ?", (e["codigo"],))]
        bd.close()
        caso("PS-08", "CU06", "Contraseñas y API Keys no se almacenan ni se devuelven en claro",
             "la API no devuelve campos hash/clave/key; BD con hash de contraseñas y SHA-256 de la API Key (no la clave)",
             f"campos filtrados={fuga}; ejemplo hash={hashes[0][:14]}…; hash key len={len(keys[0])}",
             not fuga and all(h.startswith(("bcrypt$", "scrypt$")) for h in hashes) and ADMIN_PASS not in "".join(hashes) and keys[0] != e["key"] and len(keys[0]) == 64)

    def test_ps09_cuerpo_grande(self):
        e = self.entorno()
        st, _, _, _ = http(self.url + "/mediciones", "POST", raw=b"{" + b'"a":"' + b"x" * (1024 * 1024 + 10) + b'"}', key=e["key"], headers={"Content-Type": "application/json"})
        caso("PS-09", "CU09", "Cuerpo de solicitud mayor a 1 MB", "413", f"{st}", st == 413)

    def test_ps10_json_malformado(self):
        e = self.entorno()
        a = http(self.url + "/mediciones", "POST", raw=b"{no es json", key=e["key"], headers={"Content-Type": "application/json"})[0]
        b = http(self.url + "/mediciones", "POST", raw=b"[1,2,3]", key=e["key"], headers={"Content-Type": "application/json"})[0]
        c = http(self.url + "/auth/login", "POST", raw=b"", headers={"Content-Type": "application/json"})[0]
        caso("PS-10", "CU09", "JSON malformado, tipo equivocado y cuerpo vacío no provocan error 500", "400, 422 y 400", f"{a}, {b}, {c}", (a, b, c) == (400, 422, 400))

    def test_ps11_error_sin_detalle_interno(self):
        st, js, body, _ = http(self.url + "/ruta-que-no-existe", token=self.token("enc"))
        st2, js2, body2, _ = http(self.url + "/usuarios/abc", token=self.token("admin"))
        txt = (body + body2).decode(errors="ignore")
        caso("PS-11", "—", "Errores no filtran trazas ni rutas internas", "404 sin 'Traceback' ni rutas de archivos", f"{st}/{st2}; fuga={'Traceback' in txt or '/home/' in txt}",
             st in (404,) and "Traceback" not in txt and "/home/" not in txt)

    def test_ps12_xss_almacenado_como_dato(self):
        t = self.token("enc"); payload = "<script>alert(1)</script>"
        self.api("POST", "/bitacora", {"id_cultivo": 1, "accion": "Prueba XSS", "detalle": payload}, t)
        _, lista = self.api("GET", "/bitacora", token=t)
        guardado = next(x for x in lista if x["accion"] == "Prueba XSS")["detalle"]
        caso("PS-12", "CU11", "Texto con HTML se guarda como dato literal (el escapado ocurre en la interfaz; ver PM-07)", "la API devuelve el texto tal cual, como JSON", guardado, guardado == payload)

    def test_ps13_limite_de_tasa(self):
        e = self.entorno(); codigos = []
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        for i in range(260):
            ts = (base + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            codigos.append(self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.0, "marca_tiempo": ts}, key=e["key"])[0])
        otra = self.entorno()
        ok_otra = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.0}, key=otra["key"])[0]
        caso("PS-13", "CU09", "Límite de 240 solicitudes/minuto por API Key (mitiga abuso/DoS) sin afectar a otros dispositivos",
             "las primeras 240 → 201; las siguientes → 429; otro dispositivo sigue en 201",
             f"201×{codigos.count(201)}, 429×{codigos.count(429)}; otro dispositivo {ok_otra}", codigos.count(201) == 240 and codigos.count(429) == 20 and ok_otra == 201)

    def test_ps14_tabla_usuario_intacta(self):
        # Verifica en la base real que las pruebas de inyección no alteraron el esquema.
        bd = sqlite3.connect(Base.srv.dir + "/t.db")
        tablas = {r[0] for r in bd.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        bd.close()
        req = {"usuario", "alerta", "medicion", "evento_bitacora", "dispositivo", "sensor", "umbral", "rol", "sistema", "cultivo", "respaldo"}
        caso("PS-14", "—", "Esquema íntegro tras las pruebas de inyección SQL", "las 11 tablas existen", f"faltan={req - tablas}", req <= tablas)
