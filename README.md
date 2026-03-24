# roles.tremen.tech — Explorador Catastral SII

Plataforma open source para explorar los datos catastrales públicos del Servicio de Impuestos Internos (SII) de Chile. Cubre las 346 comunas del país, 9.4 millones de predios actuales y 136 millones de registros históricos desde 2018 a 2025.

**URL en producción:** https://roles.tremen.tech
**Frontend (repo separado):** [crishernandezmaps/roles-frontend](https://github.com/crishernandezmaps/roles-frontend)

---

## Por qué es open source

Los datos catastrales del SII son públicos, pero están dispersos en archivos difíciles de consumir (CSVs de hasta 1.6 GB, sin coordenadas, con columnas desplazadas en algunas comunas). Este proyecto consolida todo en una base de datos espacial con una API moderna y un frontend visual.

Abrimos el código porque creemos que la información catastral de Chile debería ser accesible para cualquier persona — investigadores, periodistas, desarrolladores, ciudadanos. Si te sirve, úsalo. Si lo puedes mejorar, contribuye.

**Organización:** [Tremen SpA](https://tremen.tech)

---

## Cómo se construyó

Este proyecto fue desarrollado programando en conjunto con **Claude Code** (Anthropic) y revisado, validado y dirigido al 100% por un humano. Claude Code asistió en la escritura del código, la arquitectura de la API, el pipeline de datos, las optimizaciones de búsqueda espacial y la documentación. Cada decisión de diseño, cada deploy, y cada línea de código fueron verificados por el desarrollador antes de llegar a producción.

---

## Seguridad de este repositorio

Este repo es una **copia sanitizada** del código en producción. Antes de publicarlo se verificó que:

- **Cero credenciales** en el código — todos los secrets (DB, S3, HERE API, tokens) se leen de variables de entorno (`os.environ[]`), sin fallbacks hardcodeados
- **`docker-compose.yml`** usa variables `${DB_PASS}` desde `.env`, no passwords literales
- **`.env` está en `.gitignore`** — nunca se sube al repo
- **`.env.example`** incluye todas las variables necesarias como plantilla
- Se ejecutó un grep exhaustivo contra los secrets reales de producción para confirmar cero fugas

Si encuentras algo que no debería estar público, por favor abre un issue.

---

## Arquitectura

```
┌──────────────────────────────────────────────────────────┐
│                      Internet                            │
│                         │                                │
│           ┌─────────────▼──────────────┐                 │
│           │   Nginx (SSL + rate limit) │                 │
│           │   /api/* → proxy :3009     │                 │
│           │   /*     → SPA fallback    │                 │
│           └──────┬─────────────┬───────┘                 │
│                  │             │                          │
│      ┌───────────▼───┐  ┌─────▼──────────┐               │
│      │ FastAPI :3009  │  │ React SPA      │               │
│      │ (uvicorn x2)  │  │ (static files) │               │
│      └───────┬───────┘  └────────────────┘               │
│              │                                           │
│   ┌──────────▼──────────┐    ┌─────────────────┐         │
│   │ PostgreSQL 16       │    │ Hetzner S3      │         │
│   │ + PostGIS 3.5       │    │ (22.8 GB CSVs)  │         │
│   │ 127.0.0.1:5435      │    │ presigned URLs  │         │
│   │ ~145M filas          │    └─────────────────┘         │
│   └─────────────────────┘                                │
└──────────────────────────────────────────────────────────┘
```

### Stack

| Componente | Tecnología | Detalle |
|-----------|-----------|---------|
| Frontend | React 19 + Vite 7 | SPA con Leaflet, Recharts, Lucide icons |
| Backend | FastAPI (Python 3.12) | API REST, psycopg3 connection pool |
| Base de datos | PostgreSQL 16 + PostGIS 3.5 (Docker) | 3 tablas, ~145M filas, búsqueda espacial |
| Object Storage | Hetzner S3 | Bucket `siipredios`, 22.8 GB de CSVs |
| Geocoding | HERE API | Proxy desde backend, API key nunca expuesta al cliente |

---

## Lanzar tu propia instancia

### Requisitos

- Docker + Docker Compose
- Python 3.12+
- Cuenta S3 compatible (Hetzner, AWS, MinIO) con los CSVs del SII
- API key de [HERE Developer](https://developer.here.com) (gratis hasta 30K req/mes)

### 1. Clonar y configurar

```bash
git clone https://github.com/crishernandezmaps/roles-backend.git
cd roles-backend
cp .env.example .env
```

Edita `.env` con tus credenciales:

```env
DB_PASS=tu_password_seguro
S3_ENDPOINT=https://tu-endpoint-s3.com
S3_ACCESS_KEY=tu_access_key
S3_SECRET_KEY=tu_secret_key
HERE_API_KEY=tu_here_api_key
FRONTEND_URL=http://localhost:5173
```

### 2. Levantar la base de datos

```bash
docker compose up -d
```

Esto crea un container `roles-db` con PostgreSQL 16 + PostGIS 3.5, tuneado para el volumen de datos (shared_buffers=2GB, work_mem=64MB).

### 3. Crear las tablas

```bash
docker exec -i roles-db psql -U roles_app -d roles < pipeline/sql/schema.sql
```

### 4. Cargar datos (pipeline)

```bash
python -m venv .venv
source .venv/bin/activate
pip install psycopg[binary] boto3

# Configura las variables de entorno (o usa .env con python-dotenv)
export $(cat .env | xargs)

# Ejecutar pipeline completo (descarga + carga + índices)
cd pipeline
python 05_run_all.py
```

El pipeline descarga los 16 CSVs (~22.8 GB) desde S3, los carga en PostgreSQL y construye los índices. En un servidor con buena conexión toma ~30 minutos.

### 5. Levantar la API

```bash
pip install fastapi uvicorn psycopg_pool httpx boto3
cd backend
uvicorn main:app --host 0.0.0.0 --port 3009
```

La API queda disponible en `http://localhost:3009/api/health`.

### 6. Frontend (opcional)

```bash
git clone https://github.com/crishernandezmaps/roles-frontend.git
cd roles-frontend
npm install
npm run dev   # http://localhost:5173 (proxy /api → localhost:3009)
```

---

## Estructura del proyecto

```
roles-backend/
  .env.example               # Plantilla de variables de entorno
  docker-compose.yml         # Container PostgreSQL 16 + PostGIS 3.5

  backend/                   # API FastAPI
    main.py                  # Entry point + CORS + routers
    config.py                # Lee DB_DSN, API_PORT, FRONTEND_URL de env
    db.py                    # Connection pool (psycopg_pool)
    logging_config.py        # Logging estructurado
    routers/
      health.py              # GET /api/health
      predios.py             # Búsqueda, detalle, evolución, edificio, edificio3d
      estadisticas.py        # Stats por comuna, resumen nacional
      descargas.py           # Presigned URLs para descarga masiva S3
      geocode.py             # Proxy a HERE con rate limiting y cache

  pipeline/                  # Scripts de ingesta de datos
    config.py                # Configuración S3 + DB (desde env)
    01_download_csvs.py      # Descarga CSVs desde S3 a /tmp
    02_load_latest.py        # Carga último semestre → catastro_actual
    03_load_historical.py    # Carga 16 periodos → catastro_historico
    04_build_indexes.py      # Crea índices + ANALYZE
    05_run_all.py            # Orquestador (ejecuta 01-04)
    06_load_coordinates.py   # Carga lat/lon desde CSVs BCN
    07_fix_shifted_coords.py # Corrige comunas con columnas desplazadas
    08_fix_s3_csvs.py        # Repara CSVs crudos del SII en S3
    sql/
      schema.sql             # DDL de las 3 tablas
      indexes.sql            # Índices (pg_trgm GIN, GIST espacial, B-tree)
```

---

## Base de datos

### Tablas

#### `catastro_actual` (~9.4M filas)
Último semestre (2025S2), 39 columnas del SII + coordenadas geográficas.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| comuna, manzana, predio | INTEGER | PK — identifican el rol catastral |
| rc_direccion | TEXT | Dirección según el SII |
| rc_avaluo_total | BIGINT | Avalúo total CLP |
| rc_avaluo_exento | BIGINT | Avalúo exento CLP |
| dc_contribucion_semestral | BIGINT | Contribución semestral CLP |
| rc_cod_destino | TEXT | H=Habitacional, C=Comercial, etc. |
| dc_sup_terreno | NUMERIC | Superficie terreno m² |
| sup_construida_total | NUMERIC | Superficie construida m² |
| lat, lon | FLOAT | Coordenadas geográficas (BCN) |
| dc_bc1_comuna/manzana/predio | INTEGER | Bien común (para edificios) |
| materiales, calidades | TEXT | Códigos SII de materialidad y calidad |
| pisos_max | SMALLINT | Número máximo de pisos |

**Índices:** PK (comuna, manzana, predio), destino, superficie, avalúo, dirección (pg_trgm GIN), GIST espacial (lat/lon).

#### `catastro_historico` (~136.6M filas)
13 columnas clave de los 16 semestres (2018S1 → 2025S2).
PK: (comuna, manzana, predio, anio, semestre).

#### `comunas_lookup` (347 filas)
Mapeo código oficina SII → nombre comuna + región.

**Nota:** El SII usa códigos de oficina propios, NO códigos CUT estándar (ej: Ñuñoa = 15105, no 13120).

---

## API Endpoints

Base URL: `http://localhost:3009/api`

### Predios

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/predios` | Búsqueda con filtros + paginación + ranking por relevancia |
| GET | `/predios/autocomplete` | Typeahead de direcciones SII reales |
| GET | `/predios/nearby` | Búsqueda espacial por coordenadas (PostGIS ST_DWithin) |
| GET | `/predios/nearby/markers` | Markers livianos para mapa (hasta 500) |
| GET | `/predios/:c/:m/:p` | Detalle completo (39+ columnas) |
| GET | `/predios/:c/:m/:p/evolucion` | Serie temporal de avalúos (16 periodos) |
| GET | `/predios/:c/:m/:p/edificio` | Contexto del edificio (si es departamento) |
| GET | `/predios/:c/:m/:p/edificio3d` | Datos para visualización 3D isométrica |

### Estadísticas

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/estadisticas/resumen` | Stats nacionales + distribución por región y destino |
| GET | `/estadisticas/comunas` | Stats por comuna (mediana, promedio, hab/com) |
| GET | `/estadisticas/comunas/:codigo` | Detalle de una comuna |

### Descargas

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/descargas` | Lista archivos disponibles con metadata |
| GET | `/descargas/:periodo_id/url` | Genera URL presignada S3 (15 min) |

### Referencia

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/comunas` | Lista 347 comunas SII |
| GET | `/comunas/resolve?nombre=X` | Mapea nombre de comuna → código SII |
| GET | `/destinos` | Valores distintos de destino |
| GET | `/health` | Health check con conteo de filas |

### Geocoding (proxy a HERE)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/geocode?q=X` | Forward geocoding (Chile) |
| GET | `/revgeocode?lat=X&lon=X` | Reverse geocoding |

---

## Estrategia de búsqueda

La búsqueda implementa múltiples estrategias con fallback automático:

1. **Rol directo** — si el input matchea `NNNNN-NN-NN`, busca por PK (~1ms)
2. **Búsqueda espacial** — si hay coordenadas (mapa/geocoding), usa PostGIS `ST_DWithin` con auto-expansión de radio (100→200→500m)
3. **Fuzzy text** — ILIKE con `pg_trgm`, ranking por `similarity()`
4. **Cascada de fallback** (solo página 1): con número → sin número → sin filtro de comuna

La normalización de direcciones strip prefijos viales (Avenida, Calle, Pasaje) y títulos (Presidente, General, Coronel) porque el SII los abrevia.

---

## Seguridad en producción

La instancia en producción (roles.tremen.tech) implementa:

- **Secrets** — todos en `.env` (chmod 600), cargados via `EnvironmentFile` en systemd
- **DB** — usuario de la API (`roles_reader`) con solo SELECT. Puerto solo en loopback
- **API** — uvicorn con `--proxy-headers --forwarded-allow-ips 127.0.0.1`. Docs deshabilitados en prod
- **Geocoding** — API key de HERE nunca expuesta al cliente. Cache LRU bounded (2000 entries, TTL 1h)
- **Rate limiting** — Nginx: 30 req/min. Geocoding: 10/min + 200/día por IP + 25K/mes global. Descargas S3: 10/hora por IP
- **Nginx** — HSTS, CSP, X-Frame-Options DENY, nosniff
- **CORS** — solo `https://roles.tremen.tech` y `localhost:5173`
- **Firewall** — UFW deny incoming, solo 22/80/443
- **SSH** — fail2ban (5 intentos → ban 1h)
- **Docker** — container con limits (8GB RAM, 4 CPUs), puerto en loopback

---

## Códigos SII

**Destinos:** A=Agrícola, B=Agroindustrial, C=Comercio, D=Deporte, E=Educación, F=Forestal, G=Hotel, H=Habitacional, I=Industria, L=Bodega, M=Minería, O=Oficina, P=Admin Pública, Q=Culto, S=Salud, T=Transporte, V=Otros, W=Sitio Eriazo, Y=Gallineros, Z=Estacionamiento

**Materiales:** A=Acero, B=Hormigón, C=Albañilería, E=Madera, F=Adobe, G=Perfiles Metálicos, K=Prefabricado

**Calidad:** 1=Superior, 2=Media Superior, 3=Media, 4=Media Inferior, 5=Inferior

---

## Pipeline de datos

Los datos del SII se publican semestralmente. Para actualizar:

1. Subir el nuevo CSV a S3: `catastro_historico/output/catastro_{YYYY_S}.csv`
2. Agregar el periodo a `PERIODS` en `pipeline/config.py`
3. Ejecutar `python pipeline/05_run_all.py`
4. Actualizar `FILE_SIZES` y `ROW_COUNTS` en `backend/routers/descargas.py`
5. Reiniciar la API

---

## Licencia

MIT — usa, modifica, distribuye libremente. Si lo usas en algo público, un link a este repo se agradece.
