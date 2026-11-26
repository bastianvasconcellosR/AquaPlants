# Trazabilidad: caso de uso → implementación → pruebas

| CU (ES2) | Funcionalidad | Endpoint(s) | Pantalla | Roles | Pruebas |
|---|---|---|---|---|---|
| CU01 | Iniciar sesión | `POST /auth/login`, `GET /auth/me` | Login | todos | PI-01..04, PS-03, PS-04, PS-06, PM-01, PM-02, PM-09 |
| CU02 | Consultar estado actual | `GET /dashboard/estado` | Estado actual | todos | PI-27, PI-28, PI-42, PI-44, PM-03, PM-08 |
| CU03 | Visualizar alertas | `GET /alertas` | Alertas | todos | PI-26, PM-04 |
| CU04 | Gestionar alertas | `PATCH /alertas/{id}` | Alertas | todos | PI-21..25, PM-04, PM-05 |
| CU05 | Histórico y tendencias | `GET /historico` | Históricos | todos | PI-29, PI-30, PM-06 |
| CU06 | Usuarios y roles | `/usuarios`, `/roles` | Administración → Usuarios | Administrador | PI-36, PI-37, PS-02, PS-08 |
| CU07 | Sistemas, cultivos, dispositivos, sensores | `/sistemas`, `/cultivos`, `/dispositivos`, `/sensores` | Administración | Administrador (escritura) | PI-33..35, PM-10 |
| CU08 | Umbrales | `/umbrales` | Administración → Umbrales | Administrador | PU-07, PI-38, PM-11 |
| CU09 | Recibir medición | `POST /mediciones` (API Key) | — (simulador) | Dispositivo | PU-04..06, PI-05..15, PI-43, PI-44, PS-05, PS-09, PS-10, PS-13 |
| CU10 | Recibir lote | `POST /mediciones/lote` (API Key) | — (simulador) | Dispositivo | PU-08, PI-16..20, PI-45 |
| CU11 | Bitácora agrícola | `/bitacora` | Bitácora | Encargado (crea) | PI-39, PS-12, PM-07 |
| CU12 | Exportar CSV | `GET /historico/export.csv` | Históricos | Administrador, Supervisor | PI-31, PI-32 |
| CU13 | Respaldos | `/respaldos` + hilo diario | Administración → Respaldos | Administrador | PI-40, PM-12 |

## Historias de usuario (ES2) → caso de uso → implementación

| HU | Resumen | CU | Estado en el prototipo |
|---|---|---|---|
| HU01 | Estado actual con timestamp y conexión | CU02 | Implementada y probada |
| HU02 | Visualizar alertas (variable, valor, umbral) | CU03 | Implementada y probada |
| HU03 | Histórico y tendencias por período | CU05 | Implementada y probada |
| HU04 | Usuarios, roles y permisos | CU01, CU06 | Implementada y probada |
| HU05 | Sistemas, cultivos, dispositivos y sensores | CU07 | Implementada y probada |
| HU06 | Endpoint seguro de ingesta | CU09 | Implementada y probada |
| HU07 | Gestión de alertas con causa | CU04 | Implementada y probada |
| HU08 | Bitácora agrícola | CU11 | Implementada y probada |
| HU09 | Lote tras recuperar conexión | CU10 | Implementada y probada |
| HU10 | Umbrales por variable | CU08 | Implementada y probada |
| HU11 | Exportar CSV | CU12 | Implementada y probada |
| HU12 | Respaldos | CU13 | Implementada y probada |
| HU13 | Plataforma desplegada en la nube con HTTPS | — | Archivos de despliegue listos (`Dockerfile`, `render.yaml`); el despliegue lo ejecuta el equipo con `docs/DESPLIEGUE.md` |

> Nota: el plan de pruebas de la ES2 definía 24 casos (PU-01..04, PI-01..09, PR-01..04, PS-01, PM-01..06). En la ES3 se amplió a
> 83 casos automatizados (69 de API y 14 de interfaz) más 1 prueba de carga; la numeración se reordenó y los identificadores **no** coinciden uno a uno con los de la ES2.

Reglas de negocio de la ES2 implementadas: dashboard con sondeo cada 30 s; dispositivo sin conexión a los 90 s; bloqueo
a los 5 intentos fallidos durante 15 min; JWT de 60 min; lote ≤ 500 transaccional con deduplicación; rechazo de marcas
de tiempo futuras; alertas Pendiente → En proceso → Resuelta con causa obligatoria (cierre directo permitido); exportación ≤ 10.000 filas;
respaldo manual y diario (03:00 UTC) con retención de 7 días; auditoría de acciones sensibles; borrado lógico.
