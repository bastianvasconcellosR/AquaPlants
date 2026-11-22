"""Crea claves.csv a partir de demo_keys.json (local) o de claves entregadas por la app desplegada.
Uso: python claves_desde_demo.py demo_keys.json   (o: python claves_desde_demo.py AB-001=aq_1_xxx AB-002=aq_2_yyy)"""
import csv, json, sys
SENS = {"AB-001": [("ph", 5.8, 6.6), ("temperatura_agua", 19, 25), ("caudal", 1.5, 3.5)], "AB-002": [("conductividad_ec", 1.2, 2.3), ("humedad_ambiente", 45, 80)]}
a = sys.argv[1:]
claves = json.load(open(a[0])) if len(a) == 1 and a[0].endswith(".json") else dict(x.split("=", 1) for x in a)
with open("claves.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["api_key", "variable", "minimo", "maximo"])
    for cod, k in claves.items():
        for v in SENS.get(cod, []): w.writerow([k, *v])
print("claves.csv listo")
