"""Pruebas de integración (PI): API real + base de datos real (servidor levantado por tests/base.py)."""
import csv
import io
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from tests.base import ADMIN_EMAIL, ADMIN_PASS, ENC, JWT_SECRET, OFFLINE_S, Base, caso, http


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ahora():
    return datetime.now(timezone.utc)


class Autenticacion(Base):
    def test_pi01_login_ok(self):
        st, js = self.login(*ENC)
        caso("PI-01", "CU01", "Login con credenciales válidas", "200, token JWT y rol Encargado",
             f"{st} rol={js.get('usuario', {}).get('rol')} token={'sí' if js.get('token') else 'no'}",
             st == 200 and js["usuario"]["rol"] == "Encargado" and js["token"])

    def test_pi02_login_invalido(self):
        st1, a = self.login(ENC[0], "ClaveIncorrecta1")
        st2, b = self.login("noexiste@aquaplants.cl", "ClaveIncorrecta1")
        caso("PI-02", "CU01", "Credenciales inválidas: mensaje genérico (no revela si el correo existe)",
             "401 en ambos casos con el mismo mensaje", f"{st1}/{st2} «{a.get('error')}» / «{b.get('error')}»",
             st1 == st2 == 401 and a["error"] == b["error"])

    def test_pi03_usuario_desactivado(self):
        t = self.token("admin"); email = f"baja{uuid.uuid4().hex[:6]}@aquaplants.cl"
        st, u = self.api("POST", "/usuarios", {"nombre": "Temporal", "email": email, "clave": "Temporal2026x", "rol": "Encargado"}, t)
        self.api("DELETE", f"/usuarios/{u['id']}", token=t)
        st, js = self.login(email, "Temporal2026x")
        caso("PI-03", "CU01", "Usuario desactivado no puede ingresar (FA2)", "403 con aviso de contactar al Administrador",
             f"{st} {js.get('error')}", st == 403)

    def test_pi04_token_expirado(self):
        exp = jwt.encode({"sub": "1", "rol": "Administrador", "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}, JWT_SECRET, algorithm="HS256")
        st, js = self.api("GET", "/auth/me", token=exp)
        caso("PI-04", "CU01", "Token expirado es rechazado (FA3)", "401 indicando sesión expirada", f"{st} {js.get('error')}", st == 401 and "expir" in js["error"])


class Ingesta(Base):
    def test_pi05_medicion_persiste(self):
        e = self.entorno(); ts = iso(ahora() - timedelta(minutes=1))
        st, js = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.2, "marca_tiempo": ts}, key=e["key"])
        sid = self.sensor_id(e, "ph")
        st2, h = self.api("GET", f"/historico?id_sensor={sid}&desde={iso(ahora() - timedelta(hours=1))}", token=self.token("enc"))
        caso("PI-05", "CU09", "Medición válida se guarda con su marca de tiempo y aparece en el histórico",
             "201; el histórico trae 1 punto con ese valor y esa marca",
             f"{st}; total={h.get('total')} punto={h.get('puntos')}", st == 201 and h["total"] == 1 and h["puntos"][0] == {"t": ts, "v": 6.2})

    def test_pi06_sin_marca_usa_hora_servidor(self):
        e = self.entorno()
        st, js = self.api("POST", "/mediciones", {"variable": "caudal", "valor": 2.0}, key=e["key"])
        sid = self.sensor_id(e, "caudal")
        _, h = self.api("GET", f"/historico?id_sensor={sid}", token=self.token("enc"))
        t = datetime.strptime(h["puntos"][0]["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        caso("PI-06", "CU09", "Sin marca de tiempo, el servidor asigna la hora actual", "marca dentro de los últimos 30 s",
             h["puntos"][0]["t"], abs((ahora() - t).total_seconds()) < 30)

    def test_pi07_alerta_por_umbral(self):
        e = self.entorno()
        st, js = self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.9}, key=e["key"])
        al = self.alertas(e, "Pendiente")
        caso("PI-07", "CU09", "Medición fuera de umbral genera alerta Pendiente", "201 con id de alerta; alerta pH Pendiente Crítica",
             f"{st} alerta={js.get('alerta')} {[(a['variable'], a['estado'], a['severidad']) for a in al]}",
             st == 201 and js["alerta"] and len(al) == 1 and al[0]["severidad"] == "Crítica")

    def test_pi08_sin_alerta_duplicada(self):
        e = self.entorno(); t0 = ahora() - timedelta(minutes=5)
        for i in range(3):
            self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.5 + i * 0.1, "marca_tiempo": iso(t0 + timedelta(seconds=i * 30))}, key=e["key"])
        caso("PI-08", "CU09", "No se repiten alertas mientras la anterior sigue abierta", "1 sola alerta para 3 lecturas fuera de rango",
             f"{len(self.alertas(e))} alertas", len(self.alertas(e)) == 1)

    def test_pi09_valor_normal_sin_alerta(self):
        e = self.entorno()
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.1}, key=e["key"])
        caso("PI-09", "CU09", "Valor dentro del umbral no genera alerta (límite inclusivo 6.8)", "0 alertas",
             f"{len(self.alertas(e))}", not self.alertas(e) and self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.8, "marca_tiempo": iso(ahora() - timedelta(minutes=1))}, key=e["key"])[0] == 201 and not self.alertas(e))

    def test_pi10_valor_no_numerico(self):
        e = self.entorno()
        st, js = self.api("POST", "/mediciones", {"variable": "ph", "valor": "abc"}, key=e["key"])
        sid = self.sensor_id(e, "ph")
        _, h = self.api("GET", f"/historico?id_sensor={sid}", token=self.token("enc"))
        caso("PI-10", "CU09", "Valor no numérico se rechaza y no se guarda (FA1)", "422 con detalle del campo; 0 mediciones guardadas",
             f"{st} {js.get('detalles')} total={h['total']}", st == 422 and h["total"] == 0)

    def test_pi11_fuera_de_rango_fisico(self):
        e = self.entorno()
        st, js = self.api("POST", "/mediciones", {"variable": "ph", "valor": 99}, key=e["key"])
        caso("PI-11", "CU09", "Valor físicamente imposible (pH 99) es dato erróneo, no alerta", "422 y sin alertas",
             f"{st}, alertas={len(self.alertas(e))}", st == 422 and not self.alertas(e))

    def test_pi12_timestamp_futuro(self):
        e = self.entorno()
        st, js = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6, "marca_tiempo": iso(ahora() + timedelta(hours=3))}, key=e["key"])
        caso("PI-12", "CU09", "Marca de tiempo futura se rechaza", "422", f"{st} {js.get('detalles')}", st == 422)

    def test_pi13_duplicado(self):
        e = self.entorno(); ts = iso(ahora() - timedelta(minutes=2)); b = {"variable": "ph", "valor": 6, "marca_tiempo": ts}
        a, _ = self.api("POST", "/mediciones", b, key=e["key"])
        c, js = self.api("POST", "/mediciones", b, key=e["key"])
        caso("PI-13", "CU09", "Medición repetida (mismo sensor y marca) no se duplica", "1.ª 201; 2.ª 409", f"{a}, {c}", a == 201 and c == 409)

    def test_pi14_sensor_inexistente(self):
        e = self.entorno(variables=("ph",))
        st, js = self.api("POST", "/mediciones", {"variable": "caudal", "valor": 2}, key=e["key"])
        caso("PI-14", "CU09", "Variable sin sensor registrado en el dispositivo", "422 explicando que no hay sensor", f"{st} {js.get('error')}", st == 422)

    def test_pi15_api_key(self):
        e = self.entorno(); t = self.token("admin")
        sin = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6})[0]
        mala = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6}, key=e["key"][:-3] + "xxx")[0]
        formato = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6}, key="cualquier-cosa")[0]
        self.api("DELETE", f"/dispositivos/{e['disp']}", token=t)
        baja = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6}, key=e["key"])[0]
        caso("PI-15", "CU09", "API Key ausente, alterada, mal formada y de dispositivo desactivado", "401, 401, 401 y 403",
             f"{sin}, {mala}, {formato}, {baja}", (sin, mala, formato, baja) == (401, 401, 401, 403))

    def test_pi16_lote(self):
        e = self.entorno(); base = ahora() - timedelta(minutes=30)
        lote = {"mediciones": [{"variable": "ph", "valor": 6.0 + (i % 3) * 0.1, "marca_tiempo": iso(base + timedelta(seconds=30 * i))} for i in range(40)]}
        lote["mediciones"].append({"variable": "ph", "valor": 7.7, "marca_tiempo": iso(base + timedelta(seconds=30 * 41))})
        st, js = self.api("POST", "/mediciones/lote", lote, key=e["key"])
        caso("PI-16", "CU10", "Lote acumulado en desconexión: se incorpora y evalúa alertas", "201; 41 insertadas; 1 alerta",
             f"{st} {js}", st == 201 and js["insertadas"] == 41 and js["duplicadas"] == 0 and len(js["alertas"]) == 1)

    def test_pi17_lote_duplicados(self):
        e = self.entorno(); base = ahora() - timedelta(minutes=10)
        lote = {"mediciones": [{"variable": "ph", "valor": 6.0, "marca_tiempo": iso(base + timedelta(seconds=30 * i))} for i in range(5)]}
        self.api("POST", "/mediciones/lote", lote, key=e["key"])
        st, js = self.api("POST", "/mediciones/lote", lote, key=e["key"])
        caso("PI-17", "CU10", "Reenviar el mismo lote no duplica datos", "201; 0 insertadas; 5 duplicadas", f"{st} {js}",
             st == 201 and js["insertadas"] == 0 and js["duplicadas"] == 5)

    def test_pi18_lote_demasiado_grande(self):
        e = self.entorno()
        lote = {"mediciones": [{"variable": "ph", "valor": 6.0}] * 501}
        st, js = self.api("POST", "/mediciones/lote", lote, key=e["key"])
        caso("PI-18", "CU10", "Lote de 501 mediciones supera el máximo de 500", "422", f"{st}", st == 422)

    def test_pi19_lote_transaccional(self):
        e = self.entorno(variables=("ph",)); base = ahora() - timedelta(minutes=20)
        lote = {"mediciones": [{"variable": "ph", "valor": 6.0, "marca_tiempo": iso(base + timedelta(seconds=30 * i))} for i in range(5)]}
        lote["mediciones"].append({"variable": "caudal", "valor": 2.0, "marca_tiempo": iso(base)})
        st, js = self.api("POST", "/mediciones/lote", lote, key=e["key"])
        sid = self.sensor_id(e, "ph")
        _, h = self.api("GET", f"/historico?id_sensor={sid}", token=self.token("enc"))
        lote2 = {"mediciones": lote["mediciones"][:2] + [{"variable": "ph", "valor": "x"}]}
        st2, _ = self.api("POST", "/mediciones/lote", lote2, key=e["key"])
        caso("PI-19", "CU10", "Lote con un elemento inválido se rechaza completo (transaccional)", "422 en ambos; 0 mediciones guardadas",
             f"{st}/{st2} total={h['total']}", st == 422 and st2 == 422 and h["total"] == 0)

    def test_pi20_lote_orden_cronologico(self):
        e = self.entorno(); base = ahora() - timedelta(minutes=10)
        ms = [{"variable": "ph", "valor": 6.0 + i * 0.01, "marca_tiempo": iso(base + timedelta(seconds=30 * i))} for i in range(6)]
        self.api("POST", "/mediciones/lote", {"mediciones": list(reversed(ms))}, key=e["key"])
        _, h = self.api("GET", f"/historico?id_sensor={self.sensor_id(e, 'ph')}", token=self.token("enc"))
        ts = [p["t"] for p in h["puntos"]]
        caso("PI-20", "CU10", "Lote desordenado: el histórico igual queda ordenado por marca de tiempo", "6 puntos en orden ascendente",
             f"{len(ts)} ordenado={ts == sorted(ts)}", len(ts) == 6 and ts == sorted(ts))


class Alertas(Base):
    def _alerta(self):
        e = self.entorno(); self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.9}, key=e["key"])
        return e, self.alertas(e)[0]["id"]

    def test_pi21_ciclo_de_vida(self):
        e, aid = self._alerta(); t = self.token("enc")
        a, _ = self.api("PATCH", f"/alertas/{aid}", {"estado": "En proceso"}, t)
        b, _ = self.api("PATCH", f"/alertas/{aid}", {"estado": "Resuelta", "causa": "Se ajustó dosificación de ácido"}, t)
        fin = self.alertas(e)[0]
        caso("PI-21", "CU04", "Alerta: Pendiente → En proceso → Resuelta con causa", "200, 200; queda Resuelta con la causa y el usuario",
             f"{a},{b} {fin['estado']} «{fin['causa']}»", a == b == 200 and fin["estado"] == "Resuelta" and fin["causa"])

    def test_pi22_resolver_sin_causa(self):
        e, aid = self._alerta()
        st, js = self.api("PATCH", f"/alertas/{aid}", {"estado": "Resuelta"}, self.token("enc"))
        caso("PI-22", "CU04", "Resolver sin causa no está permitido", "422 pidiendo la causa; sigue Pendiente",
             f"{st} {self.alertas(e)[0]['estado']}", st == 422 and self.alertas(e)[0]["estado"] == "Pendiente")

    def test_pi23_cierre_directo(self):
        e, aid = self._alerta()
        st, _ = self.api("PATCH", f"/alertas/{aid}", {"estado": "Resuelta", "causa": "Falso positivo: sensor recién calibrado"}, self.token("sup"))
        caso("PI-23", "CU04", "Cierre directo de un falso positivo (con causa) desde Pendiente", "200 y queda Resuelta", f"{st} {self.alertas(e)[0]['estado']}",
             st == 200 and self.alertas(e)[0]["estado"] == "Resuelta")

    def test_pi24_resuelta_inmutable(self):
        e, aid = self._alerta(); t = self.token("enc")
        self.api("PATCH", f"/alertas/{aid}", {"estado": "Resuelta", "causa": "ok"}, t)
        st, _ = self.api("PATCH", f"/alertas/{aid}", {"estado": "En proceso"}, t)
        st2, _ = self.api("PATCH", f"/alertas/{aid}", {"estado": "Pendiente"}, t)
        caso("PI-24", "CU04", "Una alerta resuelta no admite cambios; estado destino inválido", "409 y 422", f"{st}, {st2}", st == 409 and st2 == 422)

    def test_pi25_alerta_inexistente(self):
        st, _ = self.api("PATCH", "/alertas/99999999", {"estado": "En proceso"}, self.token("enc"))
        caso("PI-25", "CU04", "Gestionar una alerta que no existe", "404", f"{st}", st == 404)

    def test_pi26_filtro_alertas(self):
        e, aid = self._alerta(); t = self.token("enc")
        self.api("PATCH", f"/alertas/{aid}", {"estado": "En proceso"}, t)
        pend = [a for a in self.alertas(e, "Pendiente")]; proc = self.alertas(e, "En proceso")
        malo = self.api("GET", "/alertas?estado=Inventado", token=t)[0]
        caso("PI-26", "CU03", "Listado de alertas filtrado por estado", "0 pendientes, 1 en proceso; filtro inválido → 422",
             f"{len(pend)}, {len(proc)}, {malo}", not pend and len(proc) == 1 and malo == 422)

    def test_pi27_desconexion_y_reconexion(self):
        e = self.entorno()
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.1}, key=e["key"])
        _, d1 = self.api("GET", "/dashboard/estado", token=self.token("enc"))
        en1 = next(d for d in d1["dispositivos"] if d["codigo"] == e["codigo"])["conexion"]
        time.sleep(OFFLINE_S + 1.5)
        _, d2 = self.api("GET", "/dashboard/estado", token=self.token("enc"))
        en2 = next(d for d in d2["dispositivos"] if d["codigo"] == e["codigo"])["conexion"]
        desc = [a for a in self.alertas(e) if a["tipo"] == "desconexion"]
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.2}, key=e["key"])
        _, d3 = self.api("GET", "/dashboard/estado", token=self.token("enc"))
        en3 = next(d for d in d3["dispositivos"] if d["codigo"] == e["codigo"])["conexion"]
        desc3 = [a for a in self.alertas(e) if a["tipo"] == "desconexion"]
        caso("PI-27", "CU02", f"Pérdida de comunicación (> {OFFLINE_S} s en pruebas; 90 s en producción) y reconexión",
             "en línea → sin conexión con alerta de desconexión Pendiente → al volver: en línea y alerta Resuelta automáticamente",
             f"{en1} → {en2} ({len(desc)} alerta {desc[0]['estado'] if desc else '-'}) → {en3} (alerta {desc3[0]['estado'] if desc3 else '-'})",
             (en1, en2, en3) == ("en línea", "sin conexión", "en línea") and len(desc) == 1 and desc[0]["estado"] == "Pendiente" and desc3[0]["estado"] == "Resuelta")


class Dashboard(Base):
    def test_pi28_estado_actual(self):
        e = self.entorno(); t0 = ahora() - timedelta(minutes=3)
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.0, "marca_tiempo": iso(t0)}, key=e["key"])
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.7, "marca_tiempo": iso(t0 + timedelta(minutes=1))}, key=e["key"])
        _, est = self.api("GET", "/dashboard/estado", token=self.token("enc"))
        d = next(x for x in est["dispositivos"] if x["codigo"] == e["codigo"])
        ph = next(s for s in d["sensores"] if s["variable"] == "ph"); caudal = next(s for s in d["sensores"] if s["variable"] == "caudal")
        caso("PI-28", "CU02", "Dashboard muestra la última lectura, su condición y 'sin datos' si no hay lecturas",
             "pH = 7.7 'fuera de rango'; caudal sin datos; rangos informados",
             f"pH {ph['valor']} {ph['condicion']} ({ph['minimo']}–{ph['maximo']}); caudal {caudal['condicion']}",
             ph["valor"] == 7.7 and ph["condicion"] == "fuera de rango" and caudal["condicion"] == "sin datos" and ph["maximo"] == 6.8)

    def test_pi29_historico_filtros(self):
        e = self.entorno(); base = ahora() - timedelta(days=2); sid = self.sensor_id(e, "ph")
        lote = {"mediciones": [{"variable": "ph", "valor": 6.0 + i * 0.01, "marca_tiempo": iso(base + timedelta(hours=i))} for i in range(30)]}
        self.api("POST", "/mediciones/lote", lote, key=e["key"]); t = self.token("sup")
        _, todo = self.api("GET", f"/historico?id_sensor={sid}&desde={iso(base - timedelta(hours=1))}", token=t)
        _, parte = self.api("GET", f"/historico?id_sensor={sid}&desde={iso(base + timedelta(hours=10))}&hasta={iso(base + timedelta(hours=19))}", token=t)
        _, dec = self.api("GET", f"/historico?id_sensor={sid}&desde={iso(base - timedelta(hours=1))}&max_puntos=10", token=t)
        caso("PI-29", "CU05", "Histórico por rango con estadísticas y reducción de puntos",
             "30 en total; 10 en el sub-rango; con max_puntos=10 devuelve ≤10 puntos pero total sigue 30; mín/máx/promedio correctos",
             f"{todo['total']}, {parte['total']}, {len(dec['puntos'])} (total {dec['total']}); mín {todo['minimo']} máx {todo['maximo']} prom {todo['promedio']}",
             todo["total"] == 30 and parte["total"] == 10 and len(dec["puntos"]) <= 10 and dec["total"] == 30 and todo["minimo"] == 6.0 and abs(todo["maximo"] - 6.29) < 1e-9 and abs(todo["promedio"] - 6.145) < 1e-6)

    def test_pi30_historico_errores(self):
        t = self.token("enc"); e = self.entorno(); sid = self.sensor_id(e, "ph")
        a = self.api("GET", f"/historico?id_sensor={sid}&desde=2026-10-10&hasta=2026-10-01", token=t)[0]
        b = self.api("GET", "/historico?id_sensor=99999999", token=t)[0]
        c = self.api("GET", "/historico", token=t)[0]
        d = self.api("GET", f"/historico?id_sensor={sid}&desde=basura", token=t)[0]
        f = self.api("GET", f"/historico?id_sensor={sid}&desde=2020-01-01&hasta=2026-10-01", token=t)[0]
        g = self.api("GET", f"/historico?id_sensor={sid}&desde=2026-10-05&hasta=2026-10-06", token=t)
        caso("PI-30", "CU05", "Histórico: rango invertido, sensor inexistente, sin sensor, fecha inválida, rango > 1 año y período sin datos",
             "422, 404, 422, 422, 422 y 200 con total 0", f"{a}, {b}, {c}, {d}, {f}, {g[0]} total={g[1]['total']}",
             (a, b, c, d, f) == (422, 404, 422, 422, 422) and g[0] == 200 and g[1]["total"] == 0)

    def test_pi31_exportar_csv(self):
        e = self.entorno(); base = ahora() - timedelta(hours=3); sid = self.sensor_id(e, "ph")
        self.api("POST", "/mediciones/lote", {"mediciones": [{"variable": "ph", "valor": 6.0 + i / 100, "marca_tiempo": iso(base + timedelta(minutes=i))} for i in range(12)]}, key=e["key"])
        q = f"/historico/export.csv?id_sensor={sid}&desde={iso(base - timedelta(minutes=1))}"
        st, _, body, cab = http(self.url + q, token=self.token("sup"))
        filas = list(csv.reader(io.StringIO(body.decode())))
        deny = self.api("GET", q, token=self.token("enc"))[0]
        caso("PI-31", "CU12", "Exportar CSV (Supervisor) con encabezado y filas; Encargado no puede",
             "200 text/csv; encabezado + 12 filas; Encargado 403", f"{st} {cab.get('content-type')} filas={len(filas)} cabecera={filas[0]} enc={deny}",
             st == 200 and "text/csv" in cab["content-type"] and len(filas) == 13 and filas[0][0] == "marca_tiempo" and deny == 403)

    def test_pi32_exportar_limite(self):
        e = self.entorno(variables=("ph",)); base = ahora() - timedelta(days=30)
        for k in range(21):  # 21 × 500 = 10.500 mediciones > 10.000
            lote = {"mediciones": [{"variable": "ph", "valor": 6.0, "marca_tiempo": iso(base + timedelta(seconds=30 * (k * 500 + i)))} for i in range(500)]}
            self.api("POST", "/mediciones/lote", lote, key=e["key"])
        sid = self.sensor_id(e, "ph")
        st, js = self.api("GET", f"/historico/export.csv?id_sensor={sid}&desde={iso(base - timedelta(days=1))}", token=self.token("sup"))
        acot = self.api("GET", f"/historico/export.csv?id_sensor={sid}&desde={iso(base)}&hasta={iso(base + timedelta(hours=10))}", token=self.token("sup"))[0]
        caso("PI-32", "CU12", "Exportación con más de 10.000 filas se rechaza y pide acotar", "422; acotando el rango responde 200",
             f"{st} «{(js or {}).get('error')}»; acotado {acot}", st == 422 and acot == 200)


class Administracion(Base):
    def test_pi33_crud_sistema_cultivo(self):
        t = self.token("admin"); n = uuid.uuid4().hex[:6]
        st, s = self.api("POST", "/sistemas", {"nombre": f"Sistema {n}", "ubicacion": "Bodega"}, t)
        ed = self.api("PUT", f"/sistemas/{s['id']}", {"nombre": f"Sistema {n} editado", "ubicacion": "Invernadero 2"}, t)[0]
        _, uno = self.api("GET", f"/sistemas/{s['id']}", token=t)
        st2, c = self.api("POST", "/cultivos", {"id_sistema": s["id"], "nombre": "Tomates", "especie": "Solanum lycopersicum", "fecha_inicio": "2026-10-01"}, t)
        mala = self.api("POST", "/cultivos", {"id_sistema": 999999, "nombre": "X"}, t)[0]
        fecha = self.api("POST", "/cultivos", {"id_sistema": s["id"], "nombre": "X", "fecha_inicio": "01/10/2026"}, t)[0]
        baja = self.api("DELETE", f"/cultivos/{c['id']}", token=t)
        _, cu = self.api("GET", f"/cultivos/{c['id']}", token=t)
        caso("PI-33", "CU07", "CRUD de sistema y cultivo (crear, leer, editar, desactivar) con validaciones",
             "201, 200, nombre editado, 201; cultivo con sistema inexistente 422; fecha mal formada 422; baja lógica (el registro permanece con activo=false)",
             f"{st}, {ed}, «{uno['nombre']}», {st2}; {mala}; {fecha}; baja={baja[0]} activo={cu['activo']}",
             st == 201 and ed == 200 and uno["nombre"].endswith("editado") and st2 == 201 and mala == 422 and fecha == 422 and baja[0] == 200 and cu["activo"] is False)

    def test_pi34_dispositivo_api_key(self):
        e = self.entorno(); t = self.token("admin")
        _, lista = self.api("GET", "/dispositivos", token=t)
        mio = next(d for d in lista if d["id"] == e["disp"])
        t0 = ahora()
        ok_antes = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.1, "marca_tiempo": iso(t0 - timedelta(seconds=30))}, key=e["key"])[0]
        _, nueva = self.api("POST", f"/dispositivos/{e['disp']}/regenerar-clave", token=t)
        vieja = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.2, "marca_tiempo": iso(t0 - timedelta(seconds=20))}, key=e["key"])[0]
        nueva_ok = self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.3, "marca_tiempo": iso(t0 - timedelta(seconds=10))}, key=nueva["api_key"])[0]
        caso("PI-34", "CU07", "API Key: se muestra una sola vez, no aparece en listados y al regenerar la anterior queda revocada",
             "listado sin hash ni clave; clave vieja 401 tras regenerar; la nueva 201",
             f"claves en listado={[k for k in mio if 'key' in k]}; antes {ok_antes}; vieja {vieja}; nueva {nueva_ok}",
             not [k for k in mio if "key" in k] and ok_antes == 201 and vieja == 401 and nueva_ok == 201)

    def test_pi35_dispositivo_duplicado(self):
        e = self.entorno(); t = self.token("admin")
        st, js = self.api("POST", "/dispositivos", {"id_sistema": e["sistema"], "codigo": e["codigo"], "nombre": "Otro"}, t)
        sen = self.api("POST", "/sensores", {"id_dispositivo": e["disp"], "variable": "ph"}, t)[0]
        caso("PI-35", "CU07", "Código de dispositivo duplicado y sensor duplicado", "409 y 409", f"{st}, {sen}", st == 409 and sen == 409)

    def test_pi36_usuarios(self):
        t = self.token("admin"); n = uuid.uuid4().hex[:6]; mail = f"u{n}@aquaplants.cl"
        ok = self.api("POST", "/usuarios", {"nombre": "Nuevo", "email": mail, "clave": "ClaveNueva2026", "rol": "Supervisor"}, t)[0]
        dup = self.api("POST", "/usuarios", {"nombre": "Otro", "email": mail, "clave": "ClaveNueva2026", "rol": "Supervisor"}, t)[0]
        debil = self.api("POST", "/usuarios", {"nombre": "Otro", "email": f"x{n}@aquaplants.cl", "clave": "corta1", "rol": "Supervisor"}, t)
        rol = self.api("POST", "/usuarios", {"nombre": "Otro", "email": f"y{n}@aquaplants.cl", "clave": "ClaveNueva2026", "rol": "Dios"}, t)[0]
        mal_mail = self.api("POST", "/usuarios", {"nombre": "Otro", "email": "no-es-correo", "clave": "ClaveNueva2026", "rol": "Encargado"}, t)[0]
        caso("PI-36", "CU06", "Crear usuario: correo único, política de contraseña, rol y correo válidos", "201; 409; 422 (clave); 422 (rol); 422 (correo)",
             f"{ok}; {dup}; {debil[0]}; {rol}; {mal_mail}", (ok, dup, debil[0], rol, mal_mail) == (201, 409, 422, 422, 422))

    def test_pi37_ultimo_admin(self):
        t = self.token("admin"); _, us = self.api("GET", "/usuarios", token=t)
        admins = [u for u in us if u["rol"] == "Administrador" and u["activo"]]
        a = self.api("DELETE", f"/usuarios/{admins[0]['id']}", token=t)[0] if len(admins) == 1 else None
        b = self.api("PUT", f"/usuarios/{admins[0]['id']}", {"nombre": "Administrador", "email": ADMIN_EMAIL, "rol": "Supervisor", "activo": True}, t)[0] if len(admins) == 1 else None
        caso("PI-37", "CU06", "No se puede desactivar ni degradar al último Administrador activo (FA2)", "409 y 409", f"{a}, {b} (admins activos: {len(admins)})", len(admins) == 1 and a == 409 and b == 409)

    def test_pi38_umbral_efecto(self):
        e = self.entorno(variables=("ph",)); t = self.token("admin"); sid_umb = next(u for u in self.api("GET", "/umbrales", token=t)[1] if u["id_sistema"] == e["sistema"])["id"]
        mal = self.api("PUT", f"/umbrales/{sid_umb}", {"id_sistema": e["sistema"], "variable": "ph", "minimo": 7, "maximo": 6}, t)[0]
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.0, "marca_tiempo": iso(ahora() - timedelta(minutes=2))}, key=e["key"])
        antes = len(self.alertas(e))
        ed = self.api("PUT", f"/umbrales/{sid_umb}", {"id_sistema": e["sistema"], "variable": "ph", "minimo": 5.5, "maximo": 7.5}, t)[0]
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.1, "marca_tiempo": iso(ahora() - timedelta(minutes=1))}, key=e["key"])
        despues = len(self.alertas(e))
        caso("PI-38", "CU08", "Umbral: rango inválido se rechaza; el umbral editado se aplica a las nuevas mediciones",
             "mín>máx → 422; pH 7.0 con máx 6.8 alerta (1); tras ampliar a 7.5, pH 7.1 no agrega alerta (sigue 1)",
             f"{mal}; alertas antes={antes}; edición {ed}; después={despues}", mal == 422 and antes == 1 and ed == 200 and despues == 1)

    def test_pi39_bitacora(self):
        e = self.entorno(); enc, adm, sup = self.token("enc"), self.token("admin"), self.token("sup")
        _, cultivos = self.api("GET", "/cultivos", token=enc); cid = cultivos[0]["id"]
        ok = self.api("POST", "/bitacora", {"id_cultivo": cid, "accion": "Cosecha", "detalle": "Primera cosecha de lechuga"}, enc)[0]
        adm_crea = self.api("POST", "/bitacora", {"id_cultivo": cid, "accion": "X"}, adm)[0]
        sin_cultivo = self.api("POST", "/bitacora", {"id_cultivo": 999999, "accion": "X"}, enc)[0]
        vacio = self.api("POST", "/bitacora", {"id_cultivo": cid, "accion": ""}, enc)[0]
        lista = self.api("GET", "/bitacora", token=sup)[1]
        aud_sup = self.api("GET", "/bitacora?categoria=auditoria", token=sup)[0]
        aud_adm = self.api("GET", "/bitacora?categoria=auditoria", token=adm)
        caso("PI-39", "CU11", "Bitácora agrícola: solo el Encargado registra; Supervisor lee; auditoría solo Administrador",
             "201; Admin 403; cultivo inexistente 422; acción vacía 422; lista contiene la Cosecha; auditoría: Supervisor 403, Admin 200 con eventos",
             f"{ok}; {adm_crea}; {sin_cultivo}; {vacio}; {any(x['accion'] == 'Cosecha' for x in lista)}; {aud_sup}/{aud_adm[0]} ({len(aud_adm[1])} eventos)",
             ok == 201 and adm_crea == 403 and sin_cultivo == 422 and vacio == 422 and any(x["accion"] == "Cosecha" for x in lista) and aud_sup == 403 and aud_adm[0] == 200 and len(aud_adm[1]) > 0)

    def test_pi46_informe_gestion(self):
        e = self.entorno(); t0 = ahora() - timedelta(minutes=10)
        for i, v in enumerate([6.0, 6.2, 7.9]):
            self.api("POST", "/mediciones", {"variable": "ph", "valor": v, "marca_tiempo": iso(t0 + timedelta(seconds=i * 20))}, key=e["key"])
        desde, hasta = iso(ahora() - timedelta(hours=1)), iso(ahora() + timedelta(seconds=30))
        st, r = self.api("GET", f"/informes/gestion?desde={desde}&hasta={hasta}", token=self.token("sup"))
        st_enc = self.api("GET", "/informes/gestion", token=self.token("enc"))[0]
        st_sin = self.api("GET", "/informes/gestion")[0]
        st_mal = self.api("GET", f"/informes/gestion?desde={hasta}&hasta={desde}", token=self.token("sup"))[0]
        ph = next((v for v in r.get("por_variable", []) if v["variable"] == "ph"), {})
        x = r.get("resumen", {})
        caso("PI-46", "CU14", "Informe de gestión: resumen, variables y alertas del período; solo Admin/Supervisor",
             "Supervisor 200 con ≥3 mediciones de pH, ≥1 fuera de rango y ≥1 alerta; Encargado 403; sin token 401; rango invertido 422",
             f"{st} mediciones={x.get('mediciones')} pH n={ph.get('mediciones')} fuera={ph.get('fuera_de_rango')} alertas={x.get('alertas_periodo')}; enc={st_enc}; sin={st_sin}; mal={st_mal}",
             st == 200 and ph.get("mediciones", 0) >= 3 and ph.get("fuera_de_rango", 0) >= 1 and x.get("alertas_periodo", 0) >= 1
             and "alertas" in r and st_enc == 403 and st_sin == 401 and st_mal == 422)

    def test_pi40_respaldo(self):
        t = self.token("admin")
        st, r = self.api("POST", "/respaldos", token=t)
        _, lista = self.api("GET", "/respaldos", token=t)
        deny = self.api("POST", "/respaldos", token=self.token("sup"))[0]
        caso("PI-40", "CU13", "Respaldo manual: se genera, queda en el historial; solo Administrador",
             "201 estado Completo con tamaño > 0; aparece en el listado; Supervisor 403",
             f"{st} {r}; en listado={any(x['id'] == r.get('id') for x in lista)}; sup={deny}",
             st == 201 and r["estado"] == "Completo" and r["tamano"] > 0 and any(x["id"] == r["id"] for x in lista) and deny == 403)

    def test_pi41_salud(self):
        st, js = self.api("GET", "/health")
        caso("PI-41", "—", "Endpoint de salud (usado por el despliegue)", "200 con base de datos ok", f"{st} {js}", st == 200 and js["base_de_datos"] == "ok")


class Resiliencia(Base):
    def test_pi42_monitor_sin_dashboard(self):
        e = self.entorno()
        self.api("POST", "/mediciones", {"variable": "ph", "valor": 6.1}, key=e["key"])
        time.sleep(OFFLINE_S + 3)  # nadie consulta el dashboard: lo detecta el monitor en segundo plano
        desc = [a for a in self.alertas(e) if a["tipo"] == "desconexion"]
        caso("PI-42", "CU02", "La alerta de desconexión se genera sin que nadie abra el dashboard (monitor en segundo plano)",
             "1 alerta de desconexión Pendiente creada automáticamente", f"{[(a['tipo'], a['estado']) for a in desc]}",
             len(desc) == 1 and desc[0]["estado"] == "Pendiente")

    def test_pi43_concurrencia_una_sola_alerta(self):
        import threading
        e = self.entorno(); base = ahora() - timedelta(minutes=30); res = []
        def enviar(i):
            res.append(self.api("POST", "/mediciones", {"variable": "ph", "valor": 7.5 + i / 100, "marca_tiempo": iso(base + timedelta(seconds=i))}, key=e["key"])[0])
        hilos = [threading.Thread(target=enviar, args=(i,)) for i in range(20)]
        [h.start() for h in hilos]; [h.join() for h in hilos]
        abiertas = [a for a in self.alertas(e) if a["tipo"] == "umbral" and a["estado"] != "Resuelta"]
        caso("PI-43", "CU09", "20 mediciones fuera de rango simultáneas del mismo sensor dejan una sola alerta abierta",
             "20 × 201 y exactamente 1 alerta abierta (índice único parcial)", f"{res.count(201)}×201; alertas abiertas={len(abiertas)}",
             res.count(201) == 20 and len(abiertas) == 1)


class FlujoCompleto(Base):
    """Prueba de extremo a extremo con el simulador real como cliente."""

    def _simular(self, e, *args):
        import subprocess, sys, os
        raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        r = subprocess.run([sys.executable, "simulator/simulador.py", "--url", Base.srv.url, "--clave", f"{e['codigo']}={e['key']}", *args],
                           cwd=raiz, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout

    def test_pi44_simulador_a_dashboard(self):
        e = self.entorno()
        rc, out = self._simular(e, "--escenario", "ph_alto", "--ciclos", "2", "--intervalo", "1.1")
        _, est = self.api("GET", "/dashboard/estado", token=self.token("enc"))
        d = next(x for x in est["dispositivos"] if x["codigo"] == e["codigo"])
        ph = next(s for s in d["sensores"] if s["variable"] == "ph")
        _, h = self.api("GET", f"/historico?id_sensor={self.sensor_id(e, 'ph')}", token=self.token("enc"))
        al = [a for a in self.alertas(e, "Pendiente") if a["variable"] == "ph"]
        caso("PI-44", "CU09/CU02", "Flujo completo: medición simulada → API → almacenamiento → dashboard y alerta",
             "el simulador termina bien; pH 7.9 'fuera de rango' en el dashboard; 2 puntos en el histórico; 1 alerta Pendiente",
             f"rc={rc}; pH {ph['valor']} {ph['condicion']}; {h['total']} puntos; {len(al)} alerta; conexión={d['conexion']}",
             rc == 0 and ph["valor"] == 7.9 and ph["condicion"] == "fuera de rango" and h["total"] == 2 and len(al) == 1 and d["conexion"] == "en línea")

    def test_pi45_corte_de_red_sin_perdida(self):
        e = self.entorno()
        rc, out = self._simular(e, "--escenario", "corte", "--ciclos", "6", "--ciclos-corte", "3", "--intervalo", "1.1")
        _, h = self.api("GET", f"/historico?id_sensor={self.sensor_id(e, 'caudal')}", token=self.token("enc"))
        caso("PI-45", "CU10", "Corte de red del simulador: acumula en búfer local y reenvía por lote al reconectar, sin perder datos",
             "6 ciclos → 6 mediciones por sensor en la BD; la salida muestra SIN RED y un envío de lote",
             f"rc={rc}; caudal={h['total']} puntos; 'SIN RED' en salida={'SIN RED' in out}; 'lote' en salida={'/mediciones/lote' in out or 'lote de' in out}",
             rc == 0 and h["total"] == 6 and "SIN RED" in out and "lote de" in out)


if __name__ == "__main__":
    unittest.main()
