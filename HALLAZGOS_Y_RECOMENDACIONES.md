# Discrepancias encontradas y recomendaciones

## Discrepancias (resultado esperado vs obtenido)

Se listan **todas** las discrepancias observadas durante la ejecución de pruebas, incluidas las que resultaron ser
defectos del propio script de prueba.

| ID | Prueba / origen | Esperado | Obtenido | Causa probable | Criticidad | Acción y estado |
|---|---|---|---|---|---|---|
| D-01 | PI-33 (1.ª ejecución) | `activo` devuelto como `false` al desactivar | `0` | SQLite guarda `BOOLEAN` como entero; PostgreSQL devuelve booleano: la API respondía distinto según el motor | Media | Corregido: la capa de datos normaliza `activo` a booleano. Prueba reejecutada: aprobada |
| D-02 | PI-34 (1.ª ejecución) | 201 al usar la clave nueva | 409 | Dos lecturas del mismo sensor dentro del mismo segundo se consideran duplicado (resolución de marca de tiempo de 1 s) | Baja | Comportamiento aceptado (los equipos reportan cada 30 s); prueba corregida con marcas distintas; limitación documentada (R9) |
| D-03 | PM-04 (1.ª ejecución, UI) | Aparece la alerta Pendiente | Tiempo de espera agotado | Misma causa que D-02: el script envió dos lecturas del mismo sensor en el mismo segundo y la segunda fue rechazada | Baja | Script corregido (marcas distintas). Aprobada |
| D-04 | Carga (1.ª ejecución) | 0 errores | Errores 409 | Defecto del script: generaba marcas de tiempo repetidas por sensor | Baja (defecto de la prueba) | Script corregido. Carga: 0 errores |
| D-05 | PI-26 y PS-05 (1.ª ejecución) | Respuesta HTTP | Excepción del cliente | Defecto de la prueba: URL con espacios/comillas sin codificar | Baja (defecto de la prueba) | Se codifica la URL. Aprobadas |
| D-06 | Revisión visual de PM-04 | Mensaje de alerta legible | «ph fuera de rango» (nombre interno de variable) | El mensaje usaba el identificador técnico | Baja | Corregido: «pH fuera de rango…» con nombres legibles |
| D-07 | Revisión de código al cerrar las pruebas | Alerta de desconexión siempre generada | Solo se creaba cuando alguien consultaba el dashboard; con dos solicitudes simultáneas podía duplicarse | La lógica vivía en la consulta del dashboard y la unicidad de alerta abierta se comprobaba solo en la aplicación | **Alta** | Corregido: monitor en segundo plano cada 30 s + índices únicos parciales en BD. Nuevas pruebas PI-42 y PI-43: aprobadas |
| D-08 | PI-44 (1.ª ejecución) | El escenario `ph_alto` del simulador deja el pH en 7,9 y genera alerta | pH 6,24 normal y 0 alertas | Los escenarios estaban atados al código del dispositivo de demostración (`AB-001`) y no se aplicaban a dispositivos creados por el usuario | Media | Corregido: el escenario se aplica por variable a cualquier dispositivo. Prueba reejecutada: aprobada |

## Recomendaciones priorizadas

| Prioridad | # | Recomendación | Derivada de |
|---|---|---|---|
| Alta | R1 | Ejecutar la batería completa **contra PostgreSQL** (`TEST_DATABASE_URL`, o el job `pruebas-postgres` de CI) antes de la presentación. En el entorno de desarrollo no se pudo instalar `psycopg2`, así que las 69 pruebas de API corrieron sobre SQLite; el esquema y las 69 sentencias SQL sí se validaron en PostgreSQL 16 | Limitación del entorno; D-01 muestra que SQLite y PostgreSQL pueden diferir |
| Alta | R2 | En el sitio público usar `SEED_DEMO=0` o cambiar las claves de demostración y la del administrador | Seguridad (PS-02, PS-08) |
| Alta | R3 | Definir `BACKUP_KEY` para cifrar los respaldos: contienen hashes de contraseñas y API Keys | PI-40 |
| Media | R4 | Escalar la severidad de una alerta abierta si el valor empeora (hoy no se actualiza mientras siga abierta) | PI-08 |
| Media | R5 | Si se escala a más de una instancia, mover el límite de tasa (hoy en memoria) y el respaldo diario a un servicio compartido (Redis / tarea programada externa) | PS-13 |
| Media | R6 | Ejecutar OWASP ZAP y Lighthouse (planificados en la ES2; no se ejecutaron en la ES3) y registrar sus resultados | Plan ES2 |
| Media | R7 | Evaluar guardar el token en cookie `HttpOnly` en lugar de `sessionStorage` (hoy mitigado con CSP y escapado, PM-07) | PM-07 |
| Baja | R8 | Paginación en listados de alertas y bitácora (límites actuales: 500 y 200 registros) | PI-26 |
| Baja | R9 | Aumentar la resolución de la marca de tiempo (milisegundos) si algún sensor reportara más de una vez por segundo | D-02 |
| Baja | R10 | Notificaciones por correo/mensajería para alertas críticas y sustituir el sondeo de 30 s por eventos del servidor | Alcance ES2 |
| Baja | R11 | Probar con un hardware AquaBrain real y recalibrar umbrales con datos reales | Fuera del alcance (Won't de la ES2) |

## Resultados de carga

Escenario: 20 dispositivos × 5 sensores enviando 1 lectura por sensor por segundo (≈ 30 veces la frecuencia real de
1 lectura/30 s) y 10 usuarios consultando el dashboard cada segundo, durante 40 s, SQLite en un solo servidor.
Detalle: `docs/evidencias/rendimiento.json`. Criterios de la ES2: p95 < 500 ms y errores < 1 %.
La prueba de 10 minutos con Locust de la ES2 queda disponible en `tests/locustfile.py`, pero no se ejecutó.
