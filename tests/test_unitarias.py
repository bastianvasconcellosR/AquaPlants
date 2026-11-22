"""Pruebas unitarias (PU): lógica pura, sin servidor ni base de datos."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET", "x" * 32)

from pydantic import ValidationError  # noqa: E402

from backend.app import schemas, security, services  # noqa: E402
from tests.base import caso  # noqa: E402


def falla(Esq, **datos):
    try:
        Esq(**datos)
        return None
    except ValidationError as e:
        return schemas.mensajes(e)[0]["mensaje"]


class PruebasUnitarias(unittest.TestCase):
    def test_pu01_hash_clave(self):
        h = security.hash_clave("Clave12345")
        caso("PU-01", "CU01", "La contraseña se guarda con hash y se verifica",
             "hash distinto del texto; clave correcta verifica; incorrecta no",
             f"prefijo={h.split('$')[0]}, ok={security.verificar_clave('Clave12345', h)}, mala={security.verificar_clave('otra', h)}",
             "Clave12345" not in h and security.verificar_clave("Clave12345", h) and not security.verificar_clave("clave12345", h))

    def test_pu02_hash_con_sal(self):
        a, b = security.hash_clave("MismaClave1"), security.hash_clave("MismaClave1")
        caso("PU-02", "CU01", "Dos hashes de la misma clave son distintos (sal aleatoria)", "a != b", f"iguales={a == b}", a != b)

    def test_pu03_politica_clave(self):
        r = {k: security.validar_politica(k) for k in ["corta1", "SoloLetrasLargas", "1234567890123", "Valida12345"]}
        caso("PU-03", "CU06", "Política de contraseña (≥10 caracteres, letras y números)",
             "rechaza corta, sin números y sin letras; acepta válida",
             {k: bool(v) for k, v in r.items()},
             r["corta1"] and r["SoloLetrasLargas"] and r["1234567890123"] and r["Valida12345"] is None)

    def test_pu04_medicion_valida(self):
        m = schemas.MedicionIn(variable="ph", valor=6.4, marca_tiempo="2026-10-01T10:00:00Z")
        caso("PU-04", "CU09", "Medición bien formada es aceptada", "se crea el objeto con marca UTC",
             f"{m.variable} {m.valor} {m.marca_tiempo}", m.valor == 6.4 and m.marca_tiempo.tzinfo is not None)

    def test_pu05_medicion_invalida(self):
        casos = {
            "valor texto": falla(schemas.MedicionIn, variable="ph", valor="6.5"),
            "valor booleano": falla(schemas.MedicionIn, variable="ph", valor=True),
            "NaN": falla(schemas.MedicionIn, variable="ph", valor=float("nan")),
            "fuera de rango físico": falla(schemas.MedicionIn, variable="ph", valor=99),
            "variable desconocida": falla(schemas.MedicionIn, variable="radiacion", valor=1),
            "campo extra": falla(schemas.MedicionIn, variable="ph", valor=6, extra=1),
        }
        caso("PU-05", "CU09", "Mediciones erróneas son rechazadas por el esquema",
             "los 6 casos devuelven un mensaje de error", {k: bool(v) for k, v in casos.items()}, all(casos.values()))

    def test_pu06_marca_tiempo(self):
        futuro = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        antiguo = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        justo = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
        r = (falla(schemas.MedicionIn, variable="ph", valor=6, marca_tiempo=futuro),
             falla(schemas.MedicionIn, variable="ph", valor=6, marca_tiempo=antiguo),
             falla(schemas.MedicionIn, variable="ph", valor=6, marca_tiempo=justo))
        caso("PU-06", "CU09", "Marca de tiempo: futura y muy antigua se rechazan; 20 s de desfase de reloj se tolera",
             "futuro: error; >1 año: error; +20 s: aceptada", f"{bool(r[0])}, {bool(r[1])}, {bool(r[2])}", r[0] and r[1] and r[2] is None)

    def test_pu07_umbral(self):
        r = (falla(schemas.UmbralIn, id_sistema=1, variable="ph", minimo=7, maximo=6),
             falla(schemas.UmbralIn, id_sistema=1, variable="ph", minimo=6, maximo=6),
             falla(schemas.UmbralIn, id_sistema=1, variable="ph", minimo=-3, maximo=6),
             falla(schemas.UmbralIn, id_sistema=1, variable="ph", minimo=5.5, maximo=6.8))
        caso("PU-07", "CU08", "Umbral: mínimo < máximo y dentro del rango físico",
             "mín>máx, mín=máx y fuera de rango físico fallan; 5.5–6.8 pasa", [bool(x) for x in r], r[0] and r[1] and r[2] and r[3] is None)

    def test_pu08_lote(self):
        ok = {"mediciones": [{"variable": "ph", "valor": 6}]}
        vacio = falla(schemas.LoteIn, mediciones=[])
        grande = falla(schemas.LoteIn, mediciones=[{"variable": "ph", "valor": 6}] * 501)
        caso("PU-08", "CU10", "Lote: vacío y >500 se rechazan", "vacío: error; 501: error; 1 válida: ok",
             f"vacío={bool(vacio)}, 501={bool(grande)}", vacio and grande and schemas.LoteIn(**ok))

    def test_pu09_api_key(self):
        k = security.generar_api_key(7)
        caso("PU-09", "CU07", "API Key: formato, id embebido y hash SHA-256 (no reversible)",
             "id=7; hash de 64 hex distinto de la clave; claves distintas en cada llamada",
             f"id={security.id_desde_api_key(k)}, len(hash)={len(security.hash_api_key(k))}",
             security.id_desde_api_key(k) == 7 and len(security.hash_api_key(k)) == 64 and security.hash_api_key(k) != k
             and security.generar_api_key(7) != k and security.id_desde_api_key("basura") is None)

    def test_pu10_severidad(self):
        a, b = services._severidad(6.9, 5.5, 6.8), services._severidad(7.9, 5.5, 6.8)
        caso("PU-10", "CU09", "Severidad de alerta según desvío respecto al ancho del rango",
             "6.9 → Advertencia; 7.9 → Crítica", f"{a}, {b}", a == "Advertencia" and b == "Crítica")


if __name__ == "__main__":
    unittest.main()
