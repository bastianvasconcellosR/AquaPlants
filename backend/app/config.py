"""Configuración centralizada. Todo sale de variables de entorno (ver .env.example).

Nada sensible va escrito en el código: el secreto JWT, la URL de la base de datos
y la clave de cifrado de respaldos se leen siempre desde el entorno.
"""
import os
import secrets

# Si es una URL postgresql:// se usa PostgreSQL (nube); si no, SQLite local.
# DB_EXTERNA_URL (opcional) tiene prioridad: permite apuntar a otra base (p. ej. Google Cloud SQL) sin tocar el Blueprint; al quitarla se vuelve a DATABASE_URL.
DATABASE_URL = os.getenv("DB_EXTERNA_URL") or os.getenv("DATABASE_URL", "sqlite:///./aquaplants.db")

# Render entrega "postgres://", psycopg2 espera "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

IS_PG = DATABASE_URL.startswith("postgresql://")

ENV = os.getenv("APP_ENV", "dev")  # dev | prod

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    if ENV == "prod":
        raise RuntimeError("JWT_SECRET es obligatorio en producción")
    JWT_SECRET = secrets.token_urlsafe(32)  # solo desarrollo: se pierde al reiniciar
JWT_ALG = "HS256"
JWT_MINUTOS = int(os.getenv("JWT_MINUTOS", "60"))

# Reglas de negocio definidas en la ES2
MAX_INTENTOS = int(os.getenv("MAX_INTENTOS", "5"))
BLOQUEO_MINUTOS = int(os.getenv("BLOQUEO_MINUTOS", "15"))
OFFLINE_SEGUNDOS = int(os.getenv("OFFLINE_SEGUNDOS", "90"))
MONITOR_SEGUNDOS = int(os.getenv("MONITOR_SEGUNDOS", "30"))  # 0 = desactivado
MAX_LOTE = 500
MAX_EXPORT_FILAS = 10_000
MIN_CLAVE = 10
RETENCION_RESPALDOS_DIAS = 7

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(1024 * 1024)))
RATE_LIMIT_POR_MIN = int(os.getenv("RATE_LIMIT_POR_MIN", "240"))  # por API Key

BACKUP_DIR = os.getenv("BACKUP_DIR", "./respaldos")
BACKUP_KEY = os.getenv("BACKUP_KEY")  # clave Fernet (base64 url-safe de 32 bytes)
BACKUP_HORA = os.getenv("BACKUP_HORA", "03:00")
BACKUP_AUTO = os.getenv("BACKUP_AUTO", "1") == "1"

# Datos de demostración (usuarios y sistema de ejemplo) al crear la BD vacía
SEED_DEMO = os.getenv("SEED_DEMO", "1") == "1"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@aquaplants.cl")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # si falta, se genera una y se imprime una vez

# Rangos físicamente posibles por variable: fuera de ellos el dato es erróneo (422),
# distinto de "fuera de umbral" que es un dato válido que dispara una alerta.
RANGOS_FISICOS = {
    "ph": (0.0, 14.0),
    "temperatura_agua": (-5.0, 60.0),
    "caudal": (0.0, 100.0),
    "conductividad_ec": (0.0, 20.0),
    "humedad_ambiente": (0.0, 100.0),
}
UNIDADES = {
    "ph": "pH",
    "temperatura_agua": "°C",
    "caudal": "L/min",
    "conductividad_ec": "mS/cm",
    "humedad_ambiente": "%",
}
UMBRALES_DEFECTO = {
    "ph": (5.5, 6.8),
    "temperatura_agua": (18.0, 26.0),
    "caudal": (0.5, 5.0),
    "conductividad_ec": (1.0, 2.5),
    "humedad_ambiente": (40.0, 85.0),
}
NOMBRES = {
    "ph": "pH",
    "temperatura_agua": "Temperatura del agua",
    "caudal": "Caudal",
    "conductividad_ec": "Conductividad (EC)",
    "humedad_ambiente": "Humedad ambiente",
}
