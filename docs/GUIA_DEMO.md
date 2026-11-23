# Guía para la demostración (flujo completo)

Antes: la app en la nube abierta y "despierta" (ver `DESPLIEGUE.md`), simulador listo con las API Keys.

| # | Qué mostrar | Cómo | Qué se ve |
|---|---|---|---|
| 1 | Autenticación y roles | Entrar como **encargado**, luego como **admin** | El menú cambia: solo el admin ve *Administración* |
| 2 | Estado actual | Terminal: `python simulator/simulador.py ... --intervalo 5` | Dispositivos **En línea**, valores que cambian, «hace X s» |
| 3 | Medición → API → BD → dashboard | Un ciclo del simulador y refrescar (o esperar 10 s: el panel se actualiza solo) | Valor nuevo con su marca de tiempo |
| 4 | Alerta por umbral | `--escenario ph_alto --ciclos 2` | Pantalla *Alertas*: pH Crítica Pendiente; contador en el dashboard |
| 5 | Gestión de alertas | *Tomar* → *Resolver* (pide causa; probar sin causa) | Estados y causa registrada |
| 6 | Dato erróneo | `--escenario dato_erroneo --ciclos 1` | La API responde 422 y no guarda el dato (se ve en la consola) |
| 7 | Pérdida de conexión y lote | `--escenario corte --ciclos 30 --ciclos-corte 20 --intervalo 5` (corte de ~100 s) | Tras 90 s sin datos: **Sin conexión** + alerta; al volver: lote, dispositivo **En línea**, alerta resuelta sola |
| 8 | Histórico y CSV | *Históricos* → sensor pH 24 h → *Exportar CSV* (como admin/supervisor) | Gráfico con banda del umbral y puntos rojos fuera de rango |
| 9 | CRUD | Admin → *Dispositivos → Nuevo* | Aparece la API Key **una sola vez**; crear cultivo, editar umbral, desactivar |
| 10 | Datos en la nube | Reiniciar el servicio en Render | Los datos siguen: están en PostgreSQL |
| 11 | Seguridad | Mostrar `docs/REGISTRO_PRUEBAS.md` (PS-01..14) | 401/403/423/429, inyección SQL rechazada, XSS escapado |

Tip: `python simulator/simulador.py ... --escenario ph_alto --ciclos 2` deja una alerta crítica Pendiente lista para el paso 5.
