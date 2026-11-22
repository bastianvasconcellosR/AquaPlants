# Pruebas de caja negra: carga y estrés con Apache JMeter

Caja negra: JMeter solo usa la API pública (HTTP), sin conocer el código. Plan: `tests/jmeter/aquaplants_carga.jmx`
(regenerable con `python generar_jmx.py`). Dos grupos de hilos: **Dispositivos** (POST /mediciones con X-API-Key)
y **Usuarios del dashboard** (login + GET /dashboard/estado + GET /alertas). Aserciones: 201 en ingesta, 200 en consultas.

## 1. Preparación
1. Instalar JMeter 5.6.x (requiere Java 17+) y dejar `jmeter` en el PATH (o `export JMETER=/ruta/bin/jmeter`).
2. Claves de dispositivo: local → `python claves_desde_demo.py ../../demo_keys.json`;
   nube → `python claves_desde_demo.py AB-001=<clave> AB-002=<clave>` (claves del log de arranque o regeneradas en Administración).
3. Usuario del dashboard: por defecto supervisor@aquaplants.cl / Super2026aq (`-Jemail`, `-Jclave` para cambiarlo).

## 2. Carga local (comportamiento esperado)
Levantar la app (`uvicorn backend.app.main:app` o docker compose) y ejecutar `./ejecutar.sh local`
(20 dispositivos + 10 usuarios, 30 s de subida, 120 s totales). Criterios de la ES2: p95 < 500 ms y errores < 1 %.

## 3. Estrés en la nube (punto de quiebre)
`./ejecutar.sh nube <host>.onrender.com` repite la prueba con 10, 25, 50, 100 y 200 dispositivos.
Se busca el escalón donde p95 supera 500 ms o los errores superan 1 %; ese es el límite del plan gratuito.
Antes de medir, abrir la app un minuto (arranque en frío) y no medir ese primer escalón como válido.

## 4. Qué registrar en el informe
Por escalón (informe HTML en `resultados/<escalón>/informe`): solicitudes, throughput, media, p95, p99, % error, y causa probable
(CPU del servicio, conexiones de la base, límite de 240 sol/min por API Key → 429 es esperable con pocas claves).

## 5. Advertencias
- La marca de tiempo se envía unos segundos hacia el pasado con un contador único porque la API resuelve a 1 s y rechaza duplicados (409).
- Con pocas API Keys el límite de 240/min por clave dará 429 antes que el servidor sature: para estrés real, crear más dispositivos o subir `RATE_LIMIT_POR_MIN` solo en el ambiente de prueba.
- Medir contra tu propia app desplegada, no contra servicios de terceros. El plan gratuito de Render puede suspender o limitar el servicio bajo carga fuerte.
