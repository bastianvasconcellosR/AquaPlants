"""Acceso a datos. Una sola interfaz para SQLite (desarrollo/pruebas) y PostgreSQL (nube).

Las consultas se escriben con marcadores `?` y siempre parametrizadas (nunca se
concatenan valores), lo que evita inyección SQL. En PostgreSQL el marcador se
traduce a `%s`.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()
_TRACE = os.getenv("AQ_TRACE_SQL")
_pg_pool = None


# ----------------------------------------------------------------- tiempo
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    """Formato único para guardar fechas: ISO 8601 UTC, segundos."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(v):
    """Normaliza lo que devuelva el motor (str en SQLite, datetime en PostgreSQL)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return to_iso(v)
    return str(v)


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------- esquema
def _ddl() -> str:
    pk = "SERIAL PRIMARY KEY" if config.IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMPTZ" if config.IS_PG else "TEXT"
    real = "DOUBLE PRECISION" if config.IS_PG else "REAL"
    return f"""
CREATE TABLE IF NOT EXISTS rol (
    id          {pk},
    nombre      VARCHAR(30) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS usuario (
    id                  {pk},
    nombre              VARCHAR(80)  NOT NULL,
    email               VARCHAR(120) NOT NULL UNIQUE,
    hash_clave          VARCHAR(255) NOT NULL,
    id_rol              INTEGER NOT NULL REFERENCES rol(id) ON DELETE RESTRICT,
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    intentos_fallidos   INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta     {ts},
    creado_en           {ts} NOT NULL
);

CREATE TABLE IF NOT EXISTS sistema (
    id          {pk},
    nombre      VARCHAR(80) NOT NULL UNIQUE,
    ubicacion   VARCHAR(120),
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS cultivo (
    id            {pk},
    id_sistema    INTEGER NOT NULL REFERENCES sistema(id) ON DELETE RESTRICT,
    nombre        VARCHAR(80) NOT NULL,
    especie       VARCHAR(80),
    fecha_inicio  VARCHAR(10),
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    id_encargado  INTEGER REFERENCES usuario(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS dispositivo (
    id                   {pk},
    id_sistema           INTEGER NOT NULL REFERENCES sistema(id) ON DELETE RESTRICT,
    codigo               VARCHAR(40) NOT NULL UNIQUE,
    nombre               VARCHAR(80) NOT NULL,
    tipo                 VARCHAR(40),
    hash_api_key         VARCHAR(64) NOT NULL,
    ultima_comunicacion  {ts},
    activo               BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS sensor (
    id              {pk},
    id_dispositivo  INTEGER NOT NULL REFERENCES dispositivo(id) ON DELETE RESTRICT,
    variable        VARCHAR(40) NOT NULL,
    unidad          VARCHAR(20) NOT NULL,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_sensor_disp_var UNIQUE (id_dispositivo, variable)
);

CREATE TABLE IF NOT EXISTS medicion (
    id            {pk},
    id_sensor     INTEGER NOT NULL REFERENCES sensor(id) ON DELETE RESTRICT,
    valor         {real} NOT NULL,
    marca_tiempo  {ts} NOT NULL,
    recibido_en   {ts} NOT NULL,
    CONSTRAINT uq_medicion_sensor_ts UNIQUE (id_sensor, marca_tiempo)
);

CREATE TABLE IF NOT EXISTS umbral (
    id          {pk},
    id_sistema  INTEGER NOT NULL REFERENCES sistema(id) ON DELETE RESTRICT,
    variable    VARCHAR(40) NOT NULL,
    minimo      {real} NOT NULL,
    maximo      {real} NOT NULL,
    CONSTRAINT uq_umbral_sistema_var UNIQUE (id_sistema, variable),
    CONSTRAINT ck_umbral_rango CHECK (minimo < maximo)
);

CREATE TABLE IF NOT EXISTS alerta (
    id               {pk},
    id_dispositivo   INTEGER NOT NULL REFERENCES dispositivo(id) ON DELETE RESTRICT,
    id_sensor        INTEGER REFERENCES sensor(id) ON DELETE RESTRICT,
    id_medicion      INTEGER REFERENCES medicion(id) ON DELETE RESTRICT,
    tipo             VARCHAR(20) NOT NULL,
    severidad        VARCHAR(12) NOT NULL,
    mensaje          VARCHAR(255) NOT NULL,
    valor            {real},
    estado           VARCHAR(12) NOT NULL DEFAULT 'Pendiente',
    causa            VARCHAR(255),
    creada_en        {ts} NOT NULL,
    actualizada_en   {ts},
    id_usuario       INTEGER REFERENCES usuario(id) ON DELETE RESTRICT,
    CONSTRAINT ck_alerta_estado CHECK (estado IN ('Pendiente','En proceso','Resuelta')),
    CONSTRAINT ck_alerta_tipo CHECK (tipo IN ('umbral','desconexion'))
);

CREATE TABLE IF NOT EXISTS evento_bitacora (
    id          {pk},
    categoria   VARCHAR(12) NOT NULL,
    id_usuario  INTEGER REFERENCES usuario(id) ON DELETE RESTRICT,
    id_cultivo  INTEGER REFERENCES cultivo(id) ON DELETE RESTRICT,
    accion      VARCHAR(60) NOT NULL,
    detalle     VARCHAR(500),
    creado_en   {ts} NOT NULL,
    CONSTRAINT ck_bitacora_cat CHECK (categoria IN ('agricola','auditoria'))
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave          VARCHAR(40) PRIMARY KEY,
    valor          VARCHAR(80) NOT NULL,
    actualizado_en {ts}
);

CREATE TABLE IF NOT EXISTS respaldo (
    id          {pk},
    archivo     VARCHAR(200),
    tamano      INTEGER,
    tipo        VARCHAR(12) NOT NULL,
    estado      VARCHAR(12) NOT NULL,
    id_usuario  INTEGER REFERENCES usuario(id) ON DELETE RESTRICT,
    creado_en   {ts} NOT NULL
);

-- Índices (justificación en docs/BASE_DE_DATOS.md)
CREATE INDEX IF NOT EXISTS ix_medicion_marca_tiempo ON medicion (marca_tiempo);
CREATE INDEX IF NOT EXISTS ix_alerta_estado_creada ON alerta (estado, creada_en);
CREATE INDEX IF NOT EXISTS ix_sensor_dispositivo ON sensor (id_dispositivo);
CREATE INDEX IF NOT EXISTS ix_dispositivo_sistema ON dispositivo (id_sistema);
CREATE INDEX IF NOT EXISTS ix_cultivo_sistema ON cultivo (id_sistema);
CREATE INDEX IF NOT EXISTS ix_alerta_sensor ON alerta (id_sensor);
CREATE UNIQUE INDEX IF NOT EXISTS ux_alerta_abierta_umbral ON alerta (id_sensor) WHERE tipo = 'umbral' AND estado <> 'Resuelta';
CREATE UNIQUE INDEX IF NOT EXISTS ux_alerta_abierta_desconexion ON alerta (id_dispositivo) WHERE tipo = 'desconexion' AND estado <> 'Resuelta';
CREATE INDEX IF NOT EXISTS ix_bitacora_creado ON evento_bitacora (categoria, creado_en);
"""


# ----------------------------------------------------------------- conexión
class _Conn:
    """Envuelve la conexión DB-API para ofrecer los mismos métodos en ambos motores."""

    def __init__(self, raw):
        self.raw = raw
        self.cur = raw.cursor()

    def _sql(self, sql):
        return sql.replace("?", "%s") if config.IS_PG else sql

    def execute(self, sql, params=()):
        if _TRACE:  # solo para validar las sentencias contra PostgreSQL (ver docs/BASE_DE_DATOS.md)
            with open(_TRACE, "a") as fh:
                fh.write(" ".join(sql.split()) + "\n")
        self.cur.execute(self._sql(sql), tuple(params))
        return self.cur

    def all(self, sql, params=()):
        cur = self.execute(sql, params)
        cols = [c[0] for c in cur.description]
        filas = [dict(zip(cols, r)) for r in cur.fetchall()]
        if not config.IS_PG:  # SQLite guarda BOOLEAN como 0/1; se normaliza para igualar a PostgreSQL
            for f in filas:
                if "activo" in f and f["activo"] is not None:
                    f["activo"] = bool(f["activo"])
        return filas

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def many(self, sql, filas):
        """Inserción masiva (semilla de datos de prueba)."""
        if config.IS_PG:
            from psycopg2.extras import execute_batch

            execute_batch(self.cur, self._sql(sql), [tuple(f) for f in filas], page_size=500)
        else:
            self.cur.executemany(sql, [tuple(f) for f in filas])

    def insert(self, table, data: dict) -> int:
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"
        if config.IS_PG:
            sql += " RETURNING id"
            cur = self.execute(sql, data.values())
            return cur.fetchone()[0]
        return self.execute(sql, data.values()).lastrowid

    def insert_ignore(self, table, data: dict):
        """INSERT ... ON CONFLICT DO NOTHING. Devuelve el id nuevo o None si el conflicto lo descartó."""
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT DO NOTHING"
        if config.IS_PG:
            cur = self.execute(sql + " RETURNING id", data.values())
            fila = cur.fetchone()
            return fila[0] if fila else None
        cur = self.execute(sql, data.values())
        return cur.lastrowid if cur.rowcount else None

    def update(self, table, data: dict, where: str, wparams=()):
        sets = ", ".join(f"{c} = ?" for c in data)
        self.execute(f"UPDATE {table} SET {sets} WHERE {where}", [*data.values(), *wparams])


def _new_raw():
    if config.IS_PG:
        import psycopg2  # solo se exige cuando se usa PostgreSQL

        return psycopg2.connect(config.DATABASE_URL)
    path = config.DATABASE_URL.replace("sqlite:///", "", 1)
    raw = sqlite3.connect(path, timeout=15, check_same_thread=False)
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA journal_mode = WAL")
    return raw


@contextmanager
def connect():
    """Una transacción por bloque `with`: commit al salir, rollback si hay error."""
    conn = _Conn(_new_raw())
    try:
        yield conn
        conn.raw.commit()
    except Exception:
        conn.raw.rollback()
        raise
    finally:
        conn.raw.close()


def db_path_sqlite() -> str:
    return config.DATABASE_URL.replace("sqlite:///", "", 1)


# ----------------------------------------------------------------- inicialización
ROLES = ["Administrador", "Supervisor", "Encargado"]


def _migrar(cur):
    """Cambios de esquema sobre bases ya creadas (CREATE TABLE IF NOT EXISTS no agrega columnas)."""
    if config.IS_PG:
        cur.execute("ALTER TABLE cultivo ADD COLUMN IF NOT EXISTS id_encargado INTEGER REFERENCES usuario(id) ON DELETE RESTRICT")
    else:
        cur.execute("PRAGMA table_info(cultivo)")
        if "id_encargado" not in [r[1] for r in cur.fetchall()]:
            cur.execute("ALTER TABLE cultivo ADD COLUMN id_encargado INTEGER REFERENCES usuario(id)")


def init_db():
    with _lock:
        raw = _new_raw()
        try:
            cur = raw.cursor()
            for stmt in [s for s in _ddl().split(";") if s.strip()]:
                cur.execute(stmt)
            _migrar(cur)
            raw.commit()
        finally:
            raw.close()
        with connect() as c:
            for r in ROLES:
                if not c.one("SELECT id FROM rol WHERE nombre = ?", (r,)):
                    c.insert("rol", {"nombre": r})
            from . import seed

            seed.run(c)
