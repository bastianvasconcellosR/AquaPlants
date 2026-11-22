# Checklist de presentación (10 minutos)

## La noche anterior
1. Desplegar en Render (docs/DESPLIEGUE.md) y comprobar `/api/v1/health`.
2. Entrar con admin, supervisor y encargado; crear, editar y eliminar un registro de cada tipo (CRUD).
3. Generar el Informe de gestión (24 h, 7 d, 30 d) y probar Imprimir / guardar PDF.
4. Correr el simulador contra la URL pública: `python simulator/simulador.py --url https://TU-APP.onrender.com --clave AB-001=<clave> --escenario ph_alto`.
5. Tener un hotspot del celular probado y el plan B local (`docker compose up` o `uvicorn`, con `DATABASE_URL` apuntando a la base de Render).

## 20 minutos antes
Abrir la URL para despertar el servicio (tarda ~1 min). Dejar sesiones abiertas en dos pestañas.

## Guion
1. (1 min) Qué es AquaPlants y el flujo medición → API → base → panel.
2. (3 min) CRUD en Administración sobre la base en la nube: crear dispositivo (API Key una sola vez), editar umbral, eliminar.
3. (2 min) Simulador con escenario ph_alto: la alerta aparece; tomarla y resolverla con causa.
4. (2 min) Informe de gestión y exportación a PDF.
5. (1 min) Seguridad y pruebas: 85 casos aprobados, carga JMeter.
6. (1 min) Limitaciones y recomendaciones.
