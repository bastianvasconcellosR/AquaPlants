-- Esquema PostgreSQL 16 de AquaPlants/AquaBrain (generado desde backend/app/db.py)

CREATE TABLE IF NOT EXISTS rol (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(30) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS usuario (
    id                  SERIAL PRIMARY KEY,
    nombre              VARCHAR(80)  NOT NULL,
    email               VARCHAR(120) NOT NULL UNIQUE,
    hash_clave          VARCHAR(255) NOT NULL,
    id_rol              INTEGER NOT NULL REFERENCES rol(id) ON DELETE RESTRICT,
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    intentos_fallidos   INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta     TIMESTAMPTZ,
    creado_en           TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sistema (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(80) NOT NULL UNIQUE,
    ubicacion   VARCHAR(120),
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS cultivo (
    id            SERIAL PRIMARY KEY,
    id_sistema    INTEGER NOT NULL REFERENCES sistema(id) ON DELETE RESTRICT,
    nombre        VARCHAR(80) NOT NULL,
    especie       VARCHAR(80),
    fecha_inicio  VARCHAR(10),
    activo        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS dispositivo (
    id                   SERIAL PRIMARY KEY,
    id_sistema           INTEGER NOT NULL REFERENCES sistema(id) ON DELETE RESTRICT,
    codigo               VARCHAR(40) NOT NULL UNIQUE,
    nombre               VARCHAR(80) NOT NULL,
    tipo                 VARCHAR(40),
    hash_api_key         VARCHAR(64) NOT NULL,
    ultima_comunicacion  TIMESTAMPTZ,
    activo               BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS sensor (
    id              SERIAL PRIMARY KEY,
    id_dispositivo  INTEGER NOT NULL REFERENCES dispositivo(id) ON DELETE RESTRICT,
    variable        VARCHAR(40) NOT NULL,
    unidad          VARCHAR(20) NOT NULL,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_sensor_disp_var UNIQUE (id_dispositivo, variable)
);

CREATE TABLE IF NOT EXISTS medicion (
    id            SERIAL PRIMARY KEY,
    id_sensor     INTEGER NOT NULL REFERENCES sensor(id) ON DELETE RESTRICT,
    valor         DOUBLE PRECISION NOT NULL,
    marca_tiempo  TIMESTAMPTZ NOT NULL,
    recibido_en   TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_medicion_sensor_ts UNIQUE (id_sensor, marca_tiempo)
);

CREATE TABLE IF NOT EXISTS umbral (
    id          SERIAL PRIMARY KEY,
    id_sistema  INTEGER NOT NULL REFERENCES sistema(id) ON DELETE RESTRICT,
    variable    VARCHAR(40) NOT NULL,
    minimo      DOUBLE PRECISION NOT NULL,
    maximo      DOUBLE PRECISION NOT NULL,
    CONSTRAINT uq_umbral_sistema_var UNIQUE (id_sistema, variable),
    CONSTRAINT ck_umbral_rango CHECK (minimo < maximo)
);

CREATE TABLE IF NOT EXISTS alerta (
    id               SERIAL PRIMARY KEY,
    id_dispositivo   INTEGER NOT NULL REFERENCES dispositivo(id) ON DELETE RESTRICT,
    id_sensor        INTEGER REFERENCES sensor(id) ON DELETE RESTRICT,
    id_medicion      INTEGER REFERENCES medicion(id) ON DELETE RESTRICT,
    tipo             VARCHAR(20) NOT NULL,
    severidad        VARCHAR(12) NOT NULL,
    mensaje          VARCHAR(255) NOT NULL,
    valor            DOUBLE PRECISION,
    estado           VARCHAR(12) NOT NULL DEFAULT 'Pendiente',
    causa            VARCHAR(255),
    creada_en        TIMESTAMPTZ NOT NULL,
    actualizada_en   TIMESTAMPTZ,
    id_usuario       INTEGER REFERENCES usuario(id) ON DELETE RESTRICT,
    CONSTRAINT ck_alerta_estado CHECK (estado IN ('Pendiente','En proceso','Resuelta')),
    CONSTRAINT ck_alerta_tipo CHECK (tipo IN ('umbral','desconexion'))
);

CREATE TABLE IF NOT EXISTS evento_bitacora (
    id          SERIAL PRIMARY KEY,
    categoria   VARCHAR(12) NOT NULL,
    id_usuario  INTEGER REFERENCES usuario(id) ON DELETE RESTRICT,
    id_cultivo  INTEGER REFERENCES cultivo(id) ON DELETE RESTRICT,
    accion      VARCHAR(60) NOT NULL,
    detalle     VARCHAR(500),
    creado_en   TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_bitacora_cat CHECK (categoria IN ('agricola','auditoria'))
);

CREATE TABLE IF NOT EXISTS respaldo (
    id          SERIAL PRIMARY KEY,
    archivo     VARCHAR(200),
    tamano      INTEGER,
    tipo        VARCHAR(12) NOT NULL,
    estado      VARCHAR(12) NOT NULL,
    id_usuario  INTEGER REFERENCES usuario(id) ON DELETE RESTRICT,
    creado_en   TIMESTAMPTZ NOT NULL
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
