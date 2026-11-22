"""Ejecuta TODAS las pruebas y genera la evidencia: docs/evidencias/resultados.json y docs/REGISTRO_PRUEBAS.md.
   python -m tests.run_all            (PU, PI, PS + PM de interfaz + PR de carga)
   python -m tests.run_all --rapido   (omite UI y carga)"""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime

from tests import base

EV = "docs/evidencias"


def main():
    rapido = "--rapido" in sys.argv
    os.makedirs(EV, exist_ok=True)
    suite = unittest.TestSuite()
    for mod in ("tests.test_unitarias", "tests.test_integracion", "tests.test_seguridad"):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(mod))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    api = sorted(base.REGISTRO, key=lambda r: (r["id"][:2], int(r["id"][3:])))
    ui, perf = [], None
    if not rapido:
        subprocess.run(["node", "tests/ui/pm.js"], check=False)
        ui = json.load(open(f"{EV}/ui_resultados.json"))
        subprocess.run([sys.executable, "-m", "tests.rendimiento", "40"], check=False, stdout=subprocess.DEVNULL)
        perf = json.load(open(f"{EV}/rendimiento.json"))
    json.dump({"fecha": datetime.now().isoformat(timespec="seconds"), "api": api, "ui": ui, "rendimiento": perf},
              open(f"{EV}/resultados.json", "w"), ensure_ascii=False, indent=2)
    todos = api + ui
    ok = sum(r["estado"] == "Aprobado" for r in todos)
    lineas = [f"# Registro de ejecución de pruebas", "", f"Ejecutado: {datetime.now():%Y-%m-%d %H:%M}. Resultado: **{ok}/{len(todos)} casos aprobados**"
              + (f"; carga: {'cumple' if perf['cumple'] else 'NO cumple'} los criterios." if perf else "."), ""]
    for titulo, pref in (("Unitarias (PU)", "PU"), ("Integración (PI)", "PI"), ("Seguridad (PS)", "PS"), ("Interfaz (PM)", "PM")):
        filas = [r for r in todos if r["id"].startswith(pref)]
        if not filas:
            continue
        lineas += [f"## {titulo}", "", "| ID | CU | Descripción | Resultado esperado | Resultado obtenido | Estado |", "|---|---|---|---|---|---|"]
        for r in filas:
            f = lambda t: str(t).replace("|", "\\|").replace("\n", " ")
            lineas.append(f"| {r['id']} | {r.get('cu', '—')} | {f(r['descripcion'])} | {f(r['esperado'])} | {f(r['obtenido'])} | {r['estado']} |")
        lineas.append("")
    if perf:
        lineas += ["## Carga (PR)", "", "```json", json.dumps(perf, indent=2, ensure_ascii=False), "```"]
    open("docs/REGISTRO_PRUEBAS.md", "w").write("\n".join(lineas))
    print(f"\n{ok}/{len(todos)} casos aprobados")
    sys.exit(0 if res.wasSuccessful() and ok == len(todos) else 1)


if __name__ == "__main__":
    main()
