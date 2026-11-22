# AquaPlants / AquaBrain

Plataforma web para monitorear cultivos hidropónicos/aeropónicos: recibe mediciones de dispositivos (o de un simulador),
las guarda con su marca de tiempo, evalúa umbrales, genera alertas y las muestra en un panel con histórico, bitácora
y administración por roles. Proyecto Integrado — INACAP, Ingeniería en Informática (Evaluación Sumativa 3: implementación).

## Flujo principal

```
Simulador/Dispositivo ──(API Key, JSON)──► POST /api/v1/mediciones ──► validación ──► BD (medicion)
                                                                            │
                                                          umbral superado ──┴──► alerta Pendiente
Navegador ──(JWT)──► /api/v1/dashboard/estado (cada 30 s) ──► estado actual, conexión, alertas
```

## Estructura

```
backend/app/   config.py · db.py (esquema + acceso a datos) · security.py (hash, JWT, API Key, roles)
               schemas.py (validación de entrada) · services.py (ingesta, alertas, estado, respaldos)
               api.py (endpoints /api/v1) · seed.py (datos iniciales) · main.py (aplicación ASGI)
frontend/      index.html · css/app.css · js/{api,charts,app}.js   (sin dependencias externas)
simulator/     simulador.py                                          (solo biblioteca estándar)
db/            schema_postgres.sql                                   (esquema PostgreSQL 16)
tests/         test_unitarias · test_integracion · test_seguridad · rendimiento · ui/pm.js · run_all.py
docs/          BASE_DE_DATOS.md · DESPLIEGUE.md · TRAZABILIDAD.md · REGISTRO_PRUEBAS.md · evidencias/
Dockerfile · docker-compose.yml · render.yaml · .github/workflows/ci.yml · .env.example
```

## Instalación y ejecución local

Requisitos: Python 3.11+ (probado con 3.13). Opcional: Docker, Node 18+ (solo para las pruebas de interfaz).

```bash
pip install -r requirements.txt
cp .env.example .env            # opcional; sin .env usa SQLite local y valores de desarrollo
SEED_DEMO=1 uvicorn backend.app.main:app --port 8000
# abre http://localhost:8000
```

En el primer arranque con la base vacía se crean los datos de demostración y se imprime en consola la clave del
administrador (si no definiste `ADMIN_PASSWORD`) y las API Keys de los dos dispositivos (también quedan en `demo_keys.json`).

| Usuario | Clave | Rol |
|---|---|---|
| `admin@aquaplants.cl` | la de `ADMIN_PASSWORD` o la impresa en consola | Administrador |
| `supervisor@aquaplants.cl` | `Super2026aq` | Supervisor |
| `encargado@aquaplants.cl` | `Cultivo2026aq` | Encargado |

Con Docker y PostgreSQL: `docker compose up --build` → <http://localhost:8000> (admin: `AdminLocal2026x`).

## Simulador

```bash
python simulator/simulador.py --clave-archivo demo_keys.json --intervalo 5          # operación normal
python simulator/simulador.py --clave-archivo demo_keys.json --escenario ph_alto --ciclos 2
python simulator/simulador.py --clave-archivo demo_keys.json --escenario corte --ciclos 30 --ciclos-corte 20 --intervalo 5   # corte de red + reenvío por lote
python simulator/simulador.py --url https://tu-app.onrender.com --clave AB-001=aq_1_... --clave AB-002=aq_2_...
```

Escenarios: `normal`, `ph_alto`, `temperatura_alta`, `caudal_bajo`, `ec_baja`, `dato_erroneo`, `corte`.

## API (resumen)

Documentación completa de permisos en `docs/TRAZABILIDAD.md`. Todas las rutas cuelgan de `/api/v1`.

| Grupo | Rutas |
|---|---|
| Sesión | `POST /auth/login` · `GET /auth/me` |
| Ingesta (X-API-Key) | `POST /mediciones` · `POST /mediciones/lote` (≤ 500) |
| Lectura | `GET /dashboard/estado` · `GET /alertas` · `GET /historico` · `GET /historico/export.csv` · `GET /bitacora` |
| Gestión | `PATCH /alertas/{id}` · `POST /bitacora` · CRUD de `/usuarios`, `/sistemas`, `/cultivos`, `/dispositivos`, `/sensores`, `/umbrales` · `/respaldos` |
| Salud | `GET /health` |

Ejemplo de ingesta:

```bash
curl -X POST http://localhost:8000/api/v1/mediciones -H "X-API-Key: aq_1_..." -H "Content-Type: application/json" \
     -d '{"variable":"ph","valor":6.4,"marca_tiempo":"2026-11-02T10:00:00Z"}'
```

Códigos de error: `400` JSON inválido · `401` sin sesión/clave · `403` sin permiso · `404` no existe · `409` duplicado o transición inválida ·
`413` cuerpo > 1 MB · `422` datos inválidos · `423` cuenta bloqueada · `429` límite de tasa.

## Pruebas

```bash
python -m unittest discover -s tests -t . -v        # unitarias + integración + seguridad (69 casos)
python -m pytest tests -q                           # equivalente con pytest
python -m tests.run_all                             # TODO + UI + carga, genera docs/REGISTRO_PRUEBAS.md
TEST_DATABASE_URL=postgresql://... python -m pytest tests -q    # mismas pruebas contra PostgreSQL
locust -f tests/locustfile.py --host http://localhost:8000      # carga con Locust (requiere API Keys)
```

Los resultados de la última ejecución (esperado / obtenido / estado / evidencia) están en `docs/REGISTRO_PRUEBAS.md`.

## Seguridad (resumen)

- Contraseñas con hash bcrypt (scrypt si bcrypt no está instalado), política mínima de 10 caracteres con letras y números; bloqueo de 15 min tras 5 fallos.
- Sesión con JWT firmado de 60 min; API Keys de 256 bits guardadas solo como SHA-256 y mostradas una única vez.
- Autorización por rol validada en **cada** endpoint (no solo en la interfaz).
- Validación estricta de entrada (Pydantic, `extra=forbid`), consultas siempre parametrizadas, tope de 1 MB por solicitud, límite de 240 solicitudes/min por API Key.
- Cabeceras de seguridad (CSP, `X-Frame-Options`, `nosniff`, HSTS en producción); la interfaz escapa todo texto del servidor.
- Secretos solo por variables de entorno; `.env` y `demo_keys.json` están en `.gitignore`.

## Convenciones y flujo de trabajo

- Código: Python con nombres en español del dominio, funciones cortas, una responsabilidad por módulo; JS sin dependencias.
- Git: `main` (estable) ← `develop` ← ramas `feature/*`; commits en imperativo con prefijo (`feat:`, `fix:`, `test:`, `docs:`, `infra:`); CI en GitHub Actions ejecuta las pruebas en SQLite y en PostgreSQL.
- Revisión: antes de fusionar a `develop` se ejecuta `python -m tests.run_all --rapido`.

## Limitaciones conocidas

- Resolución de marca de tiempo de 1 s: dos lecturas del mismo sensor dentro del mismo segundo se consideran duplicado.
- Límite de tasa y respaldo diario viven en memoria del proceso: usar **un solo proceso** (el `Dockerfile` ya lo hace).
- Sin HTTPS propio: se delega al proveedor (Render lo entrega); en local se usa HTTP.
- La interfaz consulta por sondeo cada 30 s (no hay WebSocket).
