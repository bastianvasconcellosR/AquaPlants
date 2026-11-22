# Base de datos — estructura, normalización e índices

Motor de producción: **PostgreSQL 16**. Para desarrollo y pruebas locales la misma aplicación acepta SQLite
(variable `DATABASE_URL`). El esquema se declara una sola vez en `backend/app/db.py` y se exporta a
`db/schema_postgres.sql`.

## Entidades y relaciones

| Tabla | Propósito | Claves y restricciones principales |
|---|---|---|
| `rol` | Roles del sistema | PK `id`; `nombre` único |
| `usuario` | Cuentas | PK; `email` único; FK `id_rol` (RESTRICT); contador de intentos y `bloqueado_hasta` |
| `sistema` | Instalación física | PK; `nombre` único |
| `cultivo` | Cultivo de un sistema | PK; FK `id_sistema` |
| `dispositivo` | Controlador AquaBrain | PK; `codigo` único; FK `id_sistema`; `hash_api_key` (SHA-256) |
| `sensor` | Variable medida por un dispositivo | PK; FK `id_dispositivo`; **único (id_dispositivo, variable)** |
| `medicion` | Lectura | PK; FK `id_sensor`; **único (id_sensor, marca_tiempo)** |
| `umbral` | Rango aceptable por variable y sistema | PK; FK `id_sistema`; único (id_sistema, variable); `CHECK minimo < maximo` |
| `alerta` | Desviación o desconexión | PK; FK dispositivo/sensor/medición/usuario; `CHECK` de estado (`Pendiente`, `En proceso`, `Resuelta`) y de tipo |
| `evento_bitacora` | Bitácora agrícola y auditoría | PK; FK usuario/cultivo; `CHECK` de categoría |
| `respaldo` | Historial de respaldos | PK; FK usuario |

Todas las claves foráneas usan `ON DELETE RESTRICT` y los registros no se borran: se **desactivan** (`activo = false`),
de modo que el histórico y la trazabilidad nunca quedan huérfanos.

## Normalización

- **1FN:** todos los atributos son atómicos; no hay listas dentro de una columna (los sensores de un dispositivo
  están en su propia tabla, no en un campo de texto).
- **2FN:** todas las tablas tienen clave primaria simple (`id`), por lo que no existen dependencias parciales.
  Las claves únicas compuestas (`id_sensor, marca_tiempo`) son restricciones de negocio, no la clave primaria.
- **3FN:** no hay dependencias transitivas. Por ejemplo, el nombre del rol no se repite en `usuario` (solo `id_rol`);
  el sistema de una medición se obtiene vía sensor → dispositivo → sistema y no se duplica.
- **Desnormalización deliberada (mínima):** `alerta.valor` y `alerta.mensaje` copian el dato del momento de la alerta.
  Es intencional: la alerta es un hecho histórico y no debe cambiar si después se edita el umbral o se corrige una medición.

## Índices y justificación

| Índice | Consulta que acelera | Evidencia (PostgreSQL 16, 300.000 mediciones) |
|---|---|---|
| `uq_medicion_sensor_ts` (id_sensor, marca_tiempo) — creado por la restricción única | Histórico por sensor y rango; última lectura de cada sensor (dashboard); garantiza que no haya duplicados | Histórico 24 h (1.439 filas): *Bitmap Index Scan*, **1,98 ms**. Última lectura: *Index Scan Backward*, **0,016 ms** |
| `ix_medicion_marca_tiempo` (marca_tiempo) | Consultas por ventana de tiempo sin filtrar sensor (conteos, exportaciones globales, purgas) | *Index Only Scan*, 0,34 ms para 2.900 filas |
| `ix_alerta_estado_creada` (estado, creada_en) | Listado de alertas abiertas ordenadas por fecha (pantalla de alertas y contadores del dashboard) | *Index Scan Backward* con `LIMIT 50` sobre 20.000 alertas: 0,03 ms |
| `ix_sensor_dispositivo`, `ix_dispositivo_sistema`, `ix_cultivo_sistema`, `ix_alerta_sensor` | Las claves foráneas no se indexan solas en PostgreSQL; evitan recorridos completos en JOIN y en verificaciones de integridad | — |
| `ux_alerta_abierta_umbral`, `ux_alerta_abierta_desconexion` (únicos parciales) | Garantizan **a nivel de base de datos** una sola alerta abierta por sensor (umbral) y por dispositivo (desconexión), incluso con solicitudes simultáneas | Comprobado en PostgreSQL y por la prueba PI-43 |
| `ix_bitacora_creado` (categoria, creado_en) | Listados de bitácora/auditoría por categoría y fecha | — |

Los planes de ejecución completos están en `docs/evidencias/postgres_validacion.txt`.

## Validación realizada

1. Esquema aplicado en PostgreSQL 16 sin errores: 11 tablas.
2. Restricciones comprobadas intentando violarlas (todas rechazadas): medición duplicada, umbral con mínimo ≥ máximo,
   estado de alerta inválido, sensor duplicado, borrado de un sistema con dispositivos y referencia a un dispositivo inexistente.
3. Las 69 sentencias SQL distintas que ejecuta la API durante las pruebas se **prepararon (`PREPARE`) en PostgreSQL 16**
   contra el esquema real: 69/69 válidas (`docs/evidencias/postgres_prepare.txt`).
4. **Limitación:** el controlador `psycopg2` no se pudo instalar en el entorno de desarrollo (sin acceso a PyPI), por lo que las
   65 pruebas automáticas se ejecutaron sobre SQLite. La misma batería puede correrse contra PostgreSQL con
   `TEST_DATABASE_URL=postgresql://... python -m pytest tests` y está configurada en CI (`.github/workflows/ci.yml`).

## Datos de prueba

Con `SEED_DEMO=1` y la base vacía se crean: 3 usuarios (uno por rol), 1 sistema, 2 cultivos, 2 dispositivos con 5 sensores,
5 umbrales por defecto, 1.445 mediciones (24 h, cada 5 min) con una excursión de pH y 1 alerta resuelta.
