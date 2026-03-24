-- Schema for roles.tremen.tech
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS postgis;

-- Latest period full detail
CREATE TABLE IF NOT EXISTS catastro_actual (
    id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    periodo                   TEXT NOT NULL,
    anio                      SMALLINT NOT NULL,
    semestre                  SMALLINT NOT NULL,
    comuna                    INTEGER NOT NULL,
    manzana                   INTEGER NOT NULL,
    predio                    INTEGER NOT NULL,
    rc_direccion              TEXT,
    rc_serie                  TEXT,
    rc_ind_aseo               TEXT,
    rc_cuota_trimestral       BIGINT,
    rc_avaluo_total           BIGINT,
    rc_avaluo_exento          BIGINT,
    rc_anio_term_exencion     SMALLINT,
    rc_cod_ubicacion          TEXT,
    rc_cod_destino            TEXT,
    dc_direccion              TEXT,
    dc_avaluo_fiscal          BIGINT,
    dc_contribucion_semestral BIGINT,
    dc_cod_destino            TEXT,
    dc_avaluo_exento          BIGINT,
    dc_sup_terreno            NUMERIC(12,2),
    dc_cod_ubicacion          TEXT,
    dc_bc1_comuna             INTEGER,
    dc_bc1_manzana            INTEGER,
    dc_bc1_predio             INTEGER,
    dc_bc2_comuna             INTEGER,
    dc_bc2_manzana            INTEGER,
    dc_bc2_predio             INTEGER,
    dc_padre_comuna           INTEGER,
    dc_padre_manzana          INTEGER,
    dc_padre_predio           INTEGER,
    n_lineas_construccion     SMALLINT,
    sup_construida_total      NUMERIC(12,2),
    anio_construccion_min     SMALLINT,
    anio_construccion_max     SMALLINT,
    materiales                TEXT,
    calidades                 TEXT,
    pisos_max                 SMALLINT,
    serie                     TEXT
    lat                       DOUBLE PRECISION,
    lon                       DOUBLE PRECISION
);

-- Historical slim table for evolution charts
CREATE TABLE IF NOT EXISTS catastro_historico (
    comuna                    INTEGER NOT NULL,
    manzana                   INTEGER NOT NULL,
    predio                    INTEGER NOT NULL,
    anio                      SMALLINT NOT NULL,
    semestre                  SMALLINT NOT NULL,
    rc_avaluo_total           BIGINT,
    rc_avaluo_exento          BIGINT,
    rc_cuota_trimestral       BIGINT,
    dc_avaluo_fiscal          BIGINT,
    dc_contribucion_semestral BIGINT,
    dc_sup_terreno            NUMERIC(12,2),
    sup_construida_total      NUMERIC(12,2),
    dc_cod_destino            TEXT,
    PRIMARY KEY (comuna, manzana, predio, anio, semestre)
);

-- Comuna lookup
CREATE TABLE IF NOT EXISTS comunas_lookup (
    codigo    INTEGER PRIMARY KEY,
    nombre    TEXT NOT NULL,
    region    TEXT NOT NULL
);
