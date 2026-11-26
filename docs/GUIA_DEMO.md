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

## Simulador: modo continuo y corte manual de un dispositivo

- **Todos los dispositivos a la vez, con alertas espontáneas** (regenera la clave de cada dispositivo):
  `python simulator\simulador.py --url URL --todos --admin-clave CLAVE --escenario aleatorio --intervalo 10`
- **Pérdida de conexión a propósito**, mientras el simulador corre (en otra ventana, en la misma carpeta):
  `echo AB-003> corte.txt` → AB-003 deja de enviar y guarda las lecturas en un búfer local; a los 90 s la app lo marca
  *Sin conexión* y genera la alerta de desconexión.
  `del corte.txt` → AB-003 se reconecta y **reenvía por lote** lo acumulado con su hora original: el histórico no pierde datos.
- Un `corte.txt` vacío corta a todos los dispositivos.

## Funciones agregadas tras la retroalimentación de la ES3
- **Desactivar / Reactivar (activo/inactivo):** el botón del CRUD ya no borra: marca el registro como inactivo y conserva su historial. Con «Mostrar inactivos» aparece el botón **Reactivar** (`POST /{recurso}/{id}/activar`). Un usuario inactivo no puede iniciar sesión y un dispositivo inactivo no puede enviar mediciones.
- **Encargado por cultivo:** pestaña **Cultivos**. El Supervisor y el Administrador eligen el encargado de cada cultivo (`PUT /cultivos/{id}/encargado`); el Encargado ve sus cultivos con «Solo mis cultivos». Cada cambio queda en la auditoría.
- **Intentos de contraseña configurables:** Administración → **Seguridad**. El Administrador define los intentos permitidos (3 a 10) y los minutos de bloqueo; se guarda en la tabla `configuracion` y se aplica de inmediato.
- **Comparación de encargados:** Informe de gestión, sección 6: cultivos a cargo, alertas atendidas y resueltas, % de resolución, tiempo medio de resolución y registros de bitácora por encargado.
