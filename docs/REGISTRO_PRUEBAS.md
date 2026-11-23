# Registro de ejecución de pruebas

Ejecutado: 2026-11-23 07:00. Resultado: **86/86 casos aprobados**; carga: cumple los criterios.

## Unitarias (PU)

| ID | CU | Descripción | Resultado esperado | Resultado obtenido | Estado |
|---|---|---|---|---|---|
| PU-01 | CU01 | La contraseña se guarda con hash y se verifica | hash distinto del texto; clave correcta verifica; incorrecta no | prefijo=scrypt, ok=True, mala=False | Aprobado |
| PU-02 | CU01 | Dos hashes de la misma clave son distintos (sal aleatoria) | a != b | iguales=False | Aprobado |
| PU-03 | CU06 | Política de contraseña (≥10 caracteres, letras y números) | rechaza corta, sin números y sin letras; acepta válida | {'corta1': True, 'SoloLetrasLargas': True, '1234567890123': True, 'Valida12345': False} | Aprobado |
| PU-04 | CU09 | Medición bien formada es aceptada | se crea el objeto con marca UTC | ph 6.4 2026-10-01 10:00:00+00:00 | Aprobado |
| PU-05 | CU09 | Mediciones erróneas son rechazadas por el esquema | los 6 casos devuelven un mensaje de error | {'valor texto': True, 'valor booleano': True, 'NaN': True, 'fuera de rango físico': True, 'variable desconocida': True, 'campo extra': True} | Aprobado |
| PU-06 | CU09 | Marca de tiempo: futura y muy antigua se rechazan; 20 s de desfase de reloj se tolera | futuro: error; >1 año: error; +20 s: aceptada | True, True, False | Aprobado |
| PU-07 | CU08 | Umbral: mínimo < máximo y dentro del rango físico | mín>máx, mín=máx y fuera de rango físico fallan; 5.5–6.8 pasa | [True, True, True, False] | Aprobado |
| PU-08 | CU10 | Lote: vacío y >500 se rechazan | vacío: error; 501: error; 1 válida: ok | vacío=True, 501=True | Aprobado |
| PU-09 | CU07 | API Key: formato, id embebido y hash SHA-256 (no reversible) | id=7; hash de 64 hex distinto de la clave; claves distintas en cada llamada | id=7, len(hash)=64 | Aprobado |
| PU-10 | CU09 | Severidad de alerta según desvío respecto al ancho del rango | 6.9 → Advertencia; 7.9 → Crítica | Advertencia, Crítica | Aprobado |

## Integración (PI)

| ID | CU | Descripción | Resultado esperado | Resultado obtenido | Estado |
|---|---|---|---|---|---|
| PI-01 | CU01 | Login con credenciales válidas | 200, token JWT y rol Encargado | 200 rol=Encargado token=sí | Aprobado |
| PI-02 | CU01 | Credenciales inválidas: mensaje genérico (no revela si el correo existe) | 401 en ambos casos con el mismo mensaje | 401/401 «Correo o contraseña incorrectos» / «Correo o contraseña incorrectos» | Aprobado |
| PI-03 | CU01 | Usuario desactivado no puede ingresar (FA2) | 403 con aviso de contactar al Administrador | 403 Usuario desactivado. Contacte al Administrador. | Aprobado |
| PI-04 | CU01 | Token expirado es rechazado (FA3) | 401 indicando sesión expirada | 401 La sesión expiró; inicie sesión nuevamente | Aprobado |
| PI-05 | CU09 | Medición válida se guarda con su marca de tiempo y aparece en el histórico | 201; el histórico trae 1 punto con ese valor y esa marca | 201; total=1 punto=[{'t': '2026-11-23T09:58:03Z', 'v': 6.2}] | Aprobado |
| PI-06 | CU09 | Sin marca de tiempo, el servidor asigna la hora actual | marca dentro de los últimos 30 s | 2026-11-23T09:59:03Z | Aprobado |
| PI-07 | CU09 | Medición fuera de umbral genera alerta Pendiente | 201 con id de alerta; alerta pH Pendiente Crítica | 201 alerta=27 [('ph', 'Pendiente', 'Crítica')] | Aprobado |
| PI-08 | CU09 | No se repiten alertas mientras la anterior sigue abierta | 1 sola alerta para 3 lecturas fuera de rango | 1 alertas | Aprobado |
| PI-09 | CU09 | Valor dentro del umbral no genera alerta (límite inclusivo 6.8) | 0 alertas | 0 | Aprobado |
| PI-10 | CU09 | Valor no numérico se rechaza y no se guarda (FA1) | 422 con detalle del campo; 0 mediciones guardadas | 422 [{'campo': 'valor', 'mensaje': 'el valor debe ser numérico'}] total=0 | Aprobado |
| PI-11 | CU09 | Valor físicamente imposible (pH 99) es dato erróneo, no alerta | 422 y sin alertas | 422, alertas=0 | Aprobado |
| PI-12 | CU09 | Marca de tiempo futura se rechaza | 422 | 422 [{'campo': 'cuerpo', 'mensaje': 'la marca de tiempo está en el futuro'}] | Aprobado |
| PI-13 | CU09 | Medición repetida (mismo sensor y marca) no se duplica | 1.ª 201; 2.ª 409 | 201, 409 | Aprobado |
| PI-14 | CU09 | Variable sin sensor registrado en el dispositivo | 422 explicando que no hay sensor | 422 El dispositivo no tiene un sensor activo para 'caudal' | Aprobado |
| PI-15 | CU09 | API Key ausente, alterada, mal formada y de dispositivo desactivado | 401, 401, 401 y 403 | 401, 401, 401, 403 | Aprobado |
| PI-16 | CU10 | Lote acumulado en desconexión: se incorpora y evalúa alertas | 201; 41 insertadas; 1 alerta | 201 {'recibidas': 41, 'insertadas': 41, 'duplicadas': 0, 'alertas': [29]} | Aprobado |
| PI-17 | CU10 | Reenviar el mismo lote no duplica datos | 201; 0 insertadas; 5 duplicadas | 201 {'recibidas': 5, 'insertadas': 0, 'duplicadas': 5, 'alertas': []} | Aprobado |
| PI-18 | CU10 | Lote de 501 mediciones supera el máximo de 500 | 422 | 422 | Aprobado |
| PI-19 | CU10 | Lote con un elemento inválido se rechaza completo (transaccional) | 422 en ambos; 0 mediciones guardadas | 422/422 total=0 | Aprobado |
| PI-20 | CU10 | Lote desordenado: el histórico igual queda ordenado por marca de tiempo | 6 puntos en orden ascendente | 6 ordenado=True | Aprobado |
| PI-21 | CU04 | Alerta: Pendiente → En proceso → Resuelta con causa | 200, 200; queda Resuelta con la causa y el usuario | 200,200 Resuelta «Se ajustó dosificación de ácido» | Aprobado |
| PI-22 | CU04 | Resolver sin causa no está permitido | 422 pidiendo la causa; sigue Pendiente | 422 Pendiente | Aprobado |
| PI-23 | CU04 | Cierre directo de un falso positivo (con causa) desde Pendiente | 200 y queda Resuelta | 200 Resuelta | Aprobado |
| PI-24 | CU04 | Una alerta resuelta no admite cambios; estado destino inválido | 409 y 422 | 409, 422 | Aprobado |
| PI-25 | CU04 | Gestionar una alerta que no existe | 404 | 404 | Aprobado |
| PI-26 | CU03 | Listado de alertas filtrado por estado | 0 pendientes, 1 en proceso; filtro inválido → 422 | 0, 1, 422 | Aprobado |
| PI-27 | CU02 | Pérdida de comunicación (> 3 s en pruebas; 90 s en producción) y reconexión | en línea → sin conexión con alerta de desconexión Pendiente → al volver: en línea y alerta Resuelta automáticamente | en línea → sin conexión (1 alerta Pendiente) → en línea (alerta Resuelta) | Aprobado |
| PI-28 | CU02 | Dashboard muestra la última lectura, su condición y 'sin datos' si no hay lecturas | pH = 7.7 'fuera de rango'; caudal sin datos; rangos informados | pH 7.7 fuera de rango (5.5–6.8); caudal sin datos | Aprobado |
| PI-29 | CU05 | Histórico por rango con estadísticas y reducción de puntos | 30 en total; 10 en el sub-rango; con max_puntos=10 devuelve ≤10 puntos pero total sigue 30; mín/máx/promedio correctos | 30, 10, 10 (total 30); mín 6.0 máx 6.29 prom 6.145 | Aprobado |
| PI-30 | CU05 | Histórico: rango invertido, sensor inexistente, sin sensor, fecha inválida, rango > 1 año y período sin datos | 422, 404, 422, 422, 422 y 200 con total 0 | 422, 404, 422, 422, 422, 200 total=0 | Aprobado |
| PI-31 | CU12 | Exportar CSV (Supervisor) con encabezado y filas; Encargado no puede | 200 text/csv; encabezado + 12 filas; Encargado 403 | 200 text/csv; charset=utf-8 filas=13 cabecera=['marca_tiempo', 'dispositivo', 'variable', 'valor', 'unidad'] enc=403 | Aprobado |
| PI-32 | CU12 | Exportación con más de 10.000 filas se rechaza y pide acotar | 422; acotando el rango responde 200 | 422 «La consulta supera 10000 filas; acote el rango o el sensor»; acotado 200 | Aprobado |
| PI-33 | CU07 | CRUD de sistema y cultivo (crear, leer, editar, desactivar) con validaciones | 201, 200, nombre editado, 201; cultivo con sistema inexistente 422; fecha mal formada 422; baja lógica (el registro permanece con activo=false) | 201, 200, «Sistema 19bdca editado», 201; 422; 422; baja=200 activo=False | Aprobado |
| PI-34 | CU07 | API Key: se muestra una sola vez, no aparece en listados y al regenerar la anterior queda revocada | listado sin hash ni clave; clave vieja 401 tras regenerar; la nueva 201 | claves en listado=[]; antes 201; vieja 401; nueva 201 | Aprobado |
| PI-35 | CU07 | Código de dispositivo duplicado y sensor duplicado | 409 y 409 | 409, 409 | Aprobado |
| PI-36 | CU06 | Crear usuario: correo único, política de contraseña, rol y correo válidos | 201; 409; 422 (clave); 422 (rol); 422 (correo) | 201; 409; 422; 422; 422 | Aprobado |
| PI-37 | CU06 | No se puede desactivar ni degradar al último Administrador activo (FA2) | 409 y 409 | 409, 409 (admins activos: 1) | Aprobado |
| PI-38 | CU08 | Umbral: rango inválido se rechaza; el umbral editado se aplica a las nuevas mediciones | mín>máx → 422; pH 7.0 con máx 6.8 alerta (1); tras ampliar a 7.5, pH 7.1 no agrega alerta (sigue 1) | 422; alertas antes=1; edición 200; después=1 | Aprobado |
| PI-39 | CU11 | Bitácora agrícola: solo el Encargado registra; Supervisor lee; auditoría solo Administrador | 201; Admin 403; cultivo inexistente 422; acción vacía 422; lista contiene la Cosecha; auditoría: Supervisor 403, Admin 200 con eventos | 201; 403; 422; 422; True; 403/200 (34 eventos) | Aprobado |
| PI-40 | CU13 | Respaldo manual: se genera, queda en el historial; solo Administrador | 201 estado Completo con tamaño > 0; aparece en el listado; Supervisor 403 | 201 {'id': 1, 'archivo': 'respaldo_20261123_095850.sqlite', 'tamano': 311296, 'estado': 'Completo'}; en listado=True; sup=403 | Aprobado |
| PI-41 | — | Endpoint de salud (usado por el despliegue) | 200 con base de datos ok | 200 {'estado': 'ok', 'base_de_datos': 'ok', 'hora': '2026-11-23T09:58:50Z'} | Aprobado |
| PI-42 | CU02 | La alerta de desconexión se genera sin que nadie abra el dashboard (monitor en segundo plano) | 1 alerta de desconexión Pendiente creada automáticamente | [('desconexion', 'Pendiente')] | Aprobado |
| PI-43 | CU09 | 20 mediciones fuera de rango simultáneas del mismo sensor dejan una sola alerta abierta | 20 × 201 y exactamente 1 alerta abierta (índice único parcial) | 20×201; alertas abiertas=1 | Aprobado |
| PI-44 | CU09/CU02 | Flujo completo: medición simulada → API → almacenamiento → dashboard y alerta | el simulador termina bien; pH 7.9 'fuera de rango' en el dashboard; 2 puntos en el histórico; 1 alerta Pendiente | rc=0; pH 7.9 fuera de rango; 2 puntos; 1 alerta; conexión=en línea | Aprobado |
| PI-45 | CU10 | Corte de red del simulador: acumula en búfer local y reenvía por lote al reconectar, sin perder datos | 6 ciclos → 6 mediciones por sensor en la BD; la salida muestra SIN RED y un envío de lote | rc=0; caudal=6 puntos; 'SIN RED' en salida=True; 'lote' en salida=True | Aprobado |
| PI-46 | CU14 | Informe de gestión: resumen, variables y alertas del período; solo Admin/Supervisor | Supervisor 200 con ≥3 mediciones de pH, ≥1 fuera de rango y ≥1 alerta; Encargado 403; sin token 401; rango invertido 422 | 200 mediciones=72 pH n=20 fuera=1 alertas=2; enc=403; sin=401; mal=422 | Aprobado |

## Seguridad (PS)

| ID | CU | Descripción | Resultado esperado | Resultado obtenido | Estado |
|---|---|---|---|---|---|
| PS-01 | CU01 | 16 endpoints protegidos sin token | todos responden 401 | todos 401 | Aprobado |
| PS-02 | CU06 | Matriz de autorización por rol (la validación ocurre en el backend) | 14 combinaciones rol/endpoint con el resultado de la matriz de la ES2 | todas coinciden | Aprobado |
| PS-03 | CU01 | Bloqueo tras 5 intentos fallidos consecutivos | 5 × 401; luego incluso la clave correcta responde 423 | [401, 401, 401, 401, 401] → clave correcta: 423 | Aprobado |
| PS-04 | CU01 | Un login correcto reinicia el contador de intentos | 4 fallos + éxito + 4 fallos + éxito → ambos 200 (no hay bloqueo) | 200, 200 | Aprobado |
| PS-05 | CU09 | Inyección SQL en login, filtros, parámetros y cuerpo | ninguna da acceso ni error 500; las tablas siguen existiendo y el login normal funciona | login [401, 401, 401, 401]; alertas [422, 422]; histórico [422, 422]; bitácora 201; login posterior 200 | Aprobado |
| PS-06 | CU01 | JWT con firma ajena, algoritmo 'none', rol alterado y basura | los 4 responden 401 | [401, 401, 401, 401] | Aprobado |
| PS-07 | — | Cabeceras de seguridad HTTP y sin caché en la API | nosniff, DENY, CSP, referrer-policy; cache-control: no-store | faltan=[]; cache-control=no-store | Aprobado |
| PS-08 | CU06 | Contraseñas y API Keys no se almacenan ni se devuelven en claro | la API no devuelve campos hash/clave/key; BD con hash de contraseñas y SHA-256 de la API Key (no la clave) | campos filtrados=[]; ejemplo hash=scrypt$VzqmH2x…; hash key len=64 | Aprobado |
| PS-09 | CU09 | Cuerpo de solicitud mayor a 1 MB | 413 | 413 | Aprobado |
| PS-10 | CU09 | JSON malformado, tipo equivocado y cuerpo vacío no provocan error 500 | 400, 422 y 400 | 400, 422, 400 | Aprobado |
| PS-11 | — | Errores no filtran trazas ni rutas internas | 404 sin 'Traceback' ni rutas de archivos | 404/404; fuga=False | Aprobado |
| PS-12 | CU11 | Texto con HTML se guarda como dato literal (el escapado ocurre en la interfaz; ver PM-07) | la API devuelve el texto tal cual, como JSON | <script>alert(1)</script> | Aprobado |
| PS-13 | CU09 | Límite de 240 solicitudes/minuto por API Key (mitiga abuso/DoS) sin afectar a otros dispositivos | las primeras 240 → 201; las siguientes → 429; otro dispositivo sigue en 201 | 201×240, 429×20; otro dispositivo 201 | Aprobado |
| PS-14 | — | Esquema íntegro tras las pruebas de inyección SQL | las 11 tablas existen | faltan=set() | Aprobado |

## Interfaz (PM)

| ID | CU | Descripción | Resultado esperado | Resultado obtenido | Estado |
|---|---|---|---|---|---|
| PM-01 | — | Login con credenciales erróneas muestra mensaje claro y no ingresa | mensaje «Correo o contraseña incorrectos»; sigue en el login | Correo o contraseña incorrectos | Aprobado |
| PM-02 | — | Login correcto del Encargado: menú acorde al rol (sin Administración) | ve Estado, Alertas, Históricos, Bitácora; no ve Administración | Estado actual, Alertas, Históricos, Bitácora | Aprobado |
| PM-03 | — | Dashboard muestra última lectura, rango, condición y conexión del dispositivo | UI-001 «En línea», pH 6.2 Normal, temperatura 22.5 Normal |   | Aprobado |
| PM-05 | — | Resolver alerta sin causa: el formulario lo impide con mensaje | mensaje indicando que la causa es obligatoria | El campo «Causa o solución aplicada» es obligatorio. | Aprobado |
| PM-04 | — | Alerta fuera de umbral: aparece Pendiente, se toma (En proceso) y se resuelve con causa | Pendiente visible → En proceso → Resuelta con la causa registrada | pendiente visible=true, en proceso=true, resuelta con causa=true | Aprobado |
| PM-06 | — | Histórico: gráfico dibujado con estadísticas; el Encargado no ve «Exportar CSV» | canvas con píxeles dibujados, 4 tarjetas de estadísticas y sin botón CSV | píxeles=175130, csv visible=false | Aprobado |
| PM-07 | — | Texto con HTML/JavaScript en la bitácora se muestra como texto y no se ejecuta (XSS) | se ve el texto literal; ningún script se ejecuta | literal visible=true, ejecuciones=0 | Aprobado |
| PM-08 | — | Pérdida de conexión del navegador con la API: aviso claro, sin pantalla en blanco | mensaje «Sin conexión con el servidor…» y/o error legible | Sin conexión con el servidor. Se muestran los últimos datos recibidos (23-11-26, 6:59:18 a. m.). Reintentando… | Aprobado |
| PM-09 | — | Token inválido/expirado: vuelve al login sin quedarse en pantalla rota | se muestra el formulario de login | login visible=true | Aprobado |
| PM-10 | — | Administrador crea dispositivo en la UI: la API Key se muestra una sola vez y no queda en la tabla | aparece diálogo con clave aq_…; luego el listado muestra el dispositivo sin la clave | clave mostrada=true, en tabla=false, dispositivo listado=true | Aprobado |
| PM-11 | — | Umbral con mínimo mayor que máximo: la API lo rechaza y la UI informa el motivo | mensaje de error visible (mínimo debe ser menor que máximo) | Datos inválidos: cuerpo – el mínimo debe ser menor que el máximo | Aprobado |
| PM-12 | — | Respaldo manual desde la UI | aparece una fila «manual» con estado Completo |  23-11-26, 6:59:22 a. m.manualrespaldo_20261123_095922.sqlite311296Completo  | Aprobado |
| PM-13 | — | Vista móvil (390 px): sin desplazamiento horizontal de la página | scrollWidth ≤ clientWidth | desborde=0px | Aprobado |
| PM-15 | — | Informe de gestión visible desde la interfaz (Administrador/Supervisor) | aparecen resumen ejecutivo, variables, desempeño por dispositivo y alertas | Período: 22-11-26, 6:59:24 a. m. a 23-11-26, 6:59:24 a. m. · Generado por Administrador el 23-11-26, 6:59:24 a | Aprobado |
| PM-16 | — | El Estado actual muestra un resumen de gestión (Administrador/Supervisor) con enlace al informe completo | aparece el resumen de 24 h y el botón lleva al informe | Resumen de gestión · últimas 24 horasVer informe completo Mediciones recibidas1443Fuera de rango0.6  | Aprobado |
| PM-14 | — | Accesibilidad básica del login: orden de tabulación y campos etiquetados | Tab recorre correo → contraseña; ambos inputs dentro de <label> | l-email → l-clave; etiquetados=true | Aprobado |

## Carga (PR)

```json
{
  "duracion_s": 40.0,
  "solicitudes": 4400,
  "throughput_rps": 109.9,
  "errores": 0,
  "tasa_error_pct": 0.0,
  "detalle_errores": [],
  "ingesta": {
    "n": 4000,
    "media_ms": 42.8,
    "p50_ms": 7.2,
    "p95_ms": 205.5,
    "p99_ms": 356.1,
    "max_ms": 566.5
  },
  "dashboard": {
    "n": 400,
    "media_ms": 75.5,
    "p50_ms": 79.2,
    "p95_ms": 99.7,
    "p99_ms": 105.6,
    "max_ms": 107.3
  },
  "cumple": true
}
```