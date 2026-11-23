# Base de datos en Google Cloud SQL (PostgreSQL)

La aplicación puede usar Google Cloud SQL sin cambiar código: la variable `DB_EXTERNA_URL` tiene prioridad sobre `DATABASE_URL`.
Para volver a la base de Render basta con **borrar** `DB_EXTERNA_URL` (el servicio se reinicia solo).

## 1. Crear la instancia
1. Consola de Google Cloud → crear un proyecto → activar la facturación (cuentas nuevas pueden tener crédito de prueba; revisar condiciones y costos vigentes).
2. Menú **SQL** → **Crear instancia** → **PostgreSQL**. Versión 15 o 16, edición Enterprise, preajuste **Sandbox** (la más económica), región `southamerica-west1` (Santiago) o la más cercana.
3. Contraseña del usuario `postgres`: **solo letras y números** (evita caracteres especiales en la URL). Conservarla.
4. En Conexiones: **IP pública** activada. En *Redes autorizadas* agregar las IP de salida de Render (Render → servicio → Connect → Outbound). Si no se pueden usar, agregar `0.0.0.0/0` **solo durante la demo** y quitarlo después; la protección queda en la contraseña y en SSL.
5. Crear la instancia (tarda varios minutos).

## 2. Crear la base y el usuario
En la instancia → **Bases de datos** → crear `aquaplants`. En **Usuarios** → crear `aquaapp` con contraseña (solo letras y números).

## 3. Conectar la aplicación
En Render → servicio `aquaplants` → **Environment** → agregar:

    DB_EXTERNA_URL = postgresql://aquaapp:CLAVE@IP_PUBLICA:5432/aquaplants?sslmode=require

Guardar. El servicio se reinicia, crea el esquema en la base nueva y, con `SEED_DEMO=1`, los usuarios y datos de demostración.
Verificar `https://TU-APP.onrender.com/api/v1/health` (debe decir `base_de_datos: ok`) y luego correr `tools/cargar_datos_demo.py` para más datos.

## 4. Ver los datos sin instalar nada
Instancia → **Cloud SQL Studio** (editor en el navegador). Iniciar con el usuario `aquaapp`. Consultas útiles:

    SELECT id, nombre FROM cultivo ORDER BY id;
    SELECT * FROM medicion ORDER BY id DESC LIMIT 20;
    SELECT estado, count(*) FROM alerta GROUP BY estado;

## 5. Volver a Render o limpiar
- Volver: borrar `DB_EXTERNA_URL` en Render.
- Al terminar la demo: detener o eliminar la instancia para no generar costos y quitar `0.0.0.0/0` si se usó.
