# Despliegue en la nube (Render + PostgreSQL)

Objetivo: tener la aplicación y su base de datos en una URL pública para la presentación.
Tiempo estimado: 15–20 minutos. Hazlo **con unos días de anticipación** y no el mismo día.

## Qué se despliega

| Pieza | Dónde | Notas |
|---|---|---|
| Aplicación (API + sitio web) | Render *Web Service* (Docker) | Un solo contenedor sirve la API `/api/v1` y la interfaz `/` |
| Base de datos | Render *PostgreSQL* | Se conecta con la variable `DATABASE_URL` |
| Simulador de dispositivos | Tu computador (o cualquier equipo) | Envía mediciones a la URL pública con la API Key del dispositivo |

## Pasos

1. **Sube el proyecto a GitHub** (repositorio propio; puede ser privado).
   ```bash
   git remote add origin https://github.com/<tu-usuario>/aquaplants.git
   git push -u origin main develop
   ```
2. Entra a <https://render.com> con tu cuenta de GitHub → **New + → Blueprint** → elige el repositorio.
   Render lee `render.yaml` y crea la base de datos `aquaplants-db` y el servicio `aquaplants`.
3. Cuando lo pida, completa **`ADMIN_PASSWORD`** (mínimo 10 caracteres, con letras y números). Es la clave del usuario
   `admin@aquaplants.cl`. `JWT_SECRET` se genera solo.
4. Espera el *build* (3–5 min). Cuando diga **Live**, abre la URL `https://aquaplants-xxxx.onrender.com`.
5. Comprueba que está sano: `https://<tu-url>/api/v1/health` debe responder `{"estado":"ok","base_de_datos":"ok",...}`.
6. **API Keys de los dispositivos de demostración:** en Render → servicio → *Logs*, busca las líneas
   `[seed] API Key de AB-001: aq_1_...`. Se imprimen una sola vez, al crear la base. Si no las alcanzaste a copiar, entra
   como administrador → *Administración → Dispositivos → Regenerar clave* (muestra la nueva clave una vez).
7. **Simulador** (en tu computador, solo necesita Python 3):
   ```bash
   python simulator/simulador.py --url https://<tu-url> --clave AB-001=aq_1_xxx --clave AB-002=aq_2_xxx --intervalo 5
   python simulator/simulador.py --url https://<tu-url> --clave AB-001=aq_1_xxx --escenario ph_alto --ciclos 2
   python simulator/simulador.py --url https://<tu-url> --clave AB-001=aq_1_xxx --clave AB-002=aq_2_xxx --escenario corte --ciclos 30 --ciclos-corte 20 --intervalo 5
   ```

Si no usas Blueprint: crea primero la base (*New + → PostgreSQL*, plan Free), copia su **Internal Database URL**, luego
*New + → Web Service → Docker* y define las variables de la tabla siguiente.

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `APP_ENV` | sí (`prod`) | En `prod` el secreto JWT es obligatorio y se activa HSTS |
| `DATABASE_URL` | sí | URL de PostgreSQL (Render la entrega con `postgres://`, la app la convierte) |
| `JWT_SECRET` | sí | Secreto de firma de sesiones (≥ 32 caracteres aleatorios) |
| `ADMIN_PASSWORD` | recomendada | Clave inicial del administrador; si falta se genera y se imprime en el log |
| `SEED_DEMO` | no | `1` crea usuarios y datos de demostración si la base está vacía |
| `BACKUP_KEY` | opcional | Clave Fernet para cifrar respaldos |

Usuarios de demostración (solo con `SEED_DEMO=1`; **cámbialos o pon `SEED_DEMO=0` si el sitio queda público**):
`supervisor@aquaplants.cl` / `Super2026aq`, `encargado@aquaplants.cl` / `Cultivo2026aq`.

## Limitaciones del plan gratuito (verificadas en la [documentación de Render](https://render.com/docs/free))

- El servicio **se duerme tras 15 minutos sin tráfico** y tarda **cerca de 1 minuto** en reactivarse: abre la URL unos
  minutos antes de presentar y deja el simulador enviando datos.
- La base de datos gratuita **expira a los 30 días de creada** (14 días de gracia antes de borrarse) y tiene 1 GB.
  Créala cerca de la fecha de presentación y descarga un respaldo (*Administración → Respaldos*) si quieres conservar los datos.
- El disco del contenedor es efímero: los respaldos `.sqlite/.json` que genera la app se pierden al reiniciar. En la nube,
  el respaldo real es el de la propia base (Render lo ofrece en planes pagos); el de la app sirve como evidencia del procedimiento.

## Alternativa 100 % local (sin cuenta cloud)

```bash
docker compose up --build        # PostgreSQL + app en http://localhost:8000
# o, sin Docker:
pip install -r requirements.txt
SEED_DEMO=1 uvicorn backend.app.main:app --port 8000
```

## Verificación posterior al despliegue

1. `/api/v1/health` → `ok`.
2. Inicia sesión con el administrador; revisa *Estado actual* (verás los dispositivos demo).
3. Ejecuta el simulador 1 ciclo: el dispositivo pasa a **En línea** y aparecen valores nuevos.
4. Ejecuta `--escenario ph_alto`: aparece una alerta crítica en *Alertas*.
5. Crea un registro (p. ej. un cultivo) y reinicia el servicio desde Render: el dato sigue ahí → los datos están en la nube.
