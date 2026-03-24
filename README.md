# roles.tremen.tech — Explorador Catastral SII

Plataforma web para explorar datos catastrales públicos del Servicio de Impuestos Internos (SII) de Chile. Cubre 346 comunas, 9.4M predios actuales y 136M registros históricos desde 2018 a 2025.

**URL:** https://roles.tremen.tech
**Organización:** Tremen SpA

---

## Stack

| Componente | Tecnología | Detalle |
|-----------|-----------|---------|
| Frontend | React 19 + Vite 7 | SPA con Leaflet, Recharts, Lucide icons |
| Backend | FastAPI (Python 3.12) | API REST, psycopg3 connection pool |
| Base de datos | PostgreSQL 16 + PostGIS 3.5 (Docker) | 3 tablas principales, ~145M filas, búsqueda espacial |
| Hosting | Hetzner VPS | 30GB RAM, 601GB disco |
| Object Storage | Hetzner S3 | Bucket `siipredios`, 22.8 GB CSVs |
| SSL | Let's Encrypt (certbot) | Auto-renewal |
| DNS | Cloudflare | A record → 46.224.221.33 |

---

## Estructura del proyecto

```
/var/www/roles.tremen.tech/
  README.md                    # Este archivo
  docker-compose.yml           # Container roles-db (PostgreSQL 16)
  .venv/                       # Python virtual environment

  pipeline/                    # Scripts de ingesta de datos
    config.py                  # Configuración S3 + DB
    01_download_csvs.py        # Descarga CSVs desde S3 a /tmp
    02_load_latest.py          # Carga último semestre → catastro_actual
    03_load_historical.py      # Carga 16 periodos → catastro_historico
    04_build_indexes.py        # Crea índices + ANALYZE
    05_run_all.py              # Orquestador (ejecuta 01-04)
    06_load_coordinates.py     # Carga lat/lon desde S3 clean CSVs → catastro_actual
    sql/
      schema.sql               # DDL de tablas
      indexes.sql              # Definición de índices

  backend/                     # FastAPI API
    main.py                    # App entry point + CORS + routers
    config.py                  # DB_DSN, API_PORT, FRONTEND_URL
    db.py                      # Connection pool (psycopg_pool)
    routers/
      __init__.py
      health.py                # GET /api/health
      predios.py               # Búsqueda, detalle, evolución, edificio, edificio3d
      estadisticas.py          # Stats por comuna, resumen nacional
      descargas.py             # Presigned URLs para descarga masiva S3

  frontend/                    # Build estático de React (dist/)
    index.html
    assets/
```

---

## Base de datos

### Container Docker

```yaml
Container: roles-db
Image: postgis/postgis:16-3.5-alpine
Port: 127.0.0.1:5435 → 5432
Database: roles
User: roles_app
Password: (set in .env)
```

Tuning: shared_buffers=2GB, work_mem=64MB, effective_cache_size=6GB

### Tablas

#### `catastro_actual` (~9.4M filas, ~5 GB)
Último semestre (2025S2), 39 columnas completas del SII.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| periodo | TEXT | "2025S2" |
| anio, semestre | SMALLINT | 2025, 2 |
| comuna | INTEGER | Código oficina SII (ej: 15105 = Ñuñoa) |
| manzana, predio | INTEGER | Identifican el rol catastral |
| rc_direccion | TEXT | Dirección del Rol Catastral |
| rc_avaluo_total | BIGINT | Avalúo total CLP |
| rc_avaluo_exento | BIGINT | Avalúo exento CLP |
| rc_cuota_trimestral | BIGINT | Cuota trimestral CLP |
| rc_cod_ubicacion | TEXT | U=Urbano, R=Rural |
| rc_cod_destino | TEXT | H=Habitacional, C=Comercial, etc. |
| dc_avaluo_fiscal | BIGINT | Avalúo fiscal CLP |
| dc_contribucion_semestral | BIGINT | Contribución semestral CLP |
| dc_sup_terreno | NUMERIC | Superficie terreno m² (0 para deptos) |
| sup_construida_total | NUMERIC | Superficie construida m² |
| dc_bc1_comuna/manzana/predio | INTEGER | Bien común (edificio) |
| n_lineas_construccion | SMALLINT | Líneas de construcción |
| anio_construccion_min/max | SMALLINT | Rango años construcción |
| materiales | TEXT | A=Acero, B=Hormigón, C=Albañilería, D=Madera, E=Adobe |
| calidades | TEXT | 1=Superior, 2=Buena, 3=Regular, 4=Económica, 5=Inferior |
| pisos_max | SMALLINT | Número máximo de pisos |

**Índices:** rol (UNIQUE), comuna, destino, superficie, avalúo, dirección (pg_trgm GIN)

#### `catastro_historico` (~136.6M filas, ~8 GB)
13 columnas clave de los 16 periodos semestrales (2018S1 → 2025S2).
PK compuesta: (comuna, manzana, predio, anio, semestre)

#### `comunas_lookup` (347 filas)
Mapeo código oficina SII → nombre comuna + región.

**IMPORTANTE:** El SII usa códigos de oficina propios, NO códigos CUT estándar.
Ejemplo: Ñuñoa = 15105 (no 13120), Providencia = 15103 (no 13132).
El mapeo se extrajo de los nombres de archivo en S3 (`2025ss/{codigo}_{NOMBRE}.csv`).

---

## API Endpoints

Base: `https://roles.tremen.tech/api`

### Predios

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/predios` | Búsqueda con filtros + paginación + ranking por relevancia |
| GET | `/predios/autocomplete` | Typeahead de direcciones SII reales |
| GET | `/predios/nearby` | Búsqueda espacial por coordenadas (PostGIS ST_DWithin) |
| GET | `/predios/:c/:m/:p` | Detalle completo (39+ cols) |
| GET | `/predios/:c/:m/:p/evolucion` | Serie temporal (16 periodos) |
| GET | `/predios/:c/:m/:p/edificio` | Contexto del edificio (si es depto) |
| GET | `/predios/:c/:m/:p/edificio3d` | Datos para visualización 3D |

**Parámetros de búsqueda `/predios`:**
- `direccion` — búsqueda fuzzy (ILIKE con pg_trgm) o búsqueda directa por rol (ej: `15103-12-45`)
- `comuna` — código SII (ahora el frontend lo resuelve automáticamente desde Nominatim)
- `destino` — H, C, I, etc.
- `sup_min`, `sup_max` — superficie efectiva (terreno o construida)
- `avaluo_min`, `avaluo_max` — avalúo total CLP
- `page`, `limit` — paginación (default 25, max 100)

**Búsqueda por rol directo:** Si `direccion` matchea el patrón `NNNNN-NN-NN`, se interpreta como rol catastral y se busca por PK (índice único, ~1ms).

**Ranking por relevancia:** Cuando hay búsqueda por dirección, los resultados se ordenan por `similarity()` de pg_trgm (mejor match primero) en vez de por rol.

**Parámetros de autocomplete `/predios/autocomplete`:**
- `q` — texto de búsqueda (mín 3 caracteres, se normaliza igual que `/predios`)
- `comuna` — código SII (opcional, acota la búsqueda)
- `limit` — máximo de sugerencias (default 8, max 20)

**Normalización de direcciones:**
El backend strip prefijos viales (Avenida, Calle, Pasaje, etc.) y títulos
(Presidente, General, Coronel, etc.) porque el SII los abrevia (PDTE, GRAL, CNEL).
Las palabras se unen con `%` para ILIKE flexible.

**Parámetros de búsqueda espacial `/predios/nearby`:**
- `lat` — latitud del punto (float, requerido)
- `lon` — longitud del punto (float, requerido)
- `radius` — radio de búsqueda en metros (int, default 100, max 500)
- `page`, `limit` — paginación (default 25, max 100)

**Auto-expansión de radio:** Si no hay resultados en el radio solicitado, se auto-expande a 200m y luego 500m.

**Respuesta adicional:** Incluye `distancia_m` por predio, `radius_used` (radio efectivo), `coordinates` (lat/lon del punto).

**Requisitos:** PostGIS 3.5, columnas `lat`/`lon` en `catastro_actual`, índice GIST espacial.
Coordenadas cargadas desde `s3://siipredios/2025ss_bcn/sii_data_clean/` via `pipeline/06_load_coordinates.py`.

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
| GET | `/comunas/resolve` | Mapea nombre de comuna → código SII (exact + fuzzy) |
| GET | `/destinos` | Valores distintos de destino |
| GET | `/health` | Health check con conteo de filas |

---

## Frontend — Páginas

| Ruta | Página | Descripción |
|------|--------|-------------|
| `/` | Home | Búsqueda dual (dirección + rol SII) con mapa + resultados |
| `/buscar` | Buscar | Tabla con filtros avanzados |
| `/predio/:c/:m/:p` | Detalle | 39+ columnas + gráficos evolución + edificio 3D |
| `/estadisticas` | Estadísticas | Charts por región/destino + tabla por comuna |
| `/descargas` | Descargas | Download masivo de CSVs por semestre |

### Modos de búsqueda

**1. Por dirección (AddressSearch):** input con autocomplete dual
- Nominatim (geocoding → mapa) + direcciones SII reales en paralelo
- **Búsqueda espacial (primaria):** coordenadas de Nominatim/mapa → `/api/predios/nearby` (PostGIS, ~5ms)
- **Fallback a texto:** si no hay resultados espaciales, usa string matching (ILIKE + pg_trgm)
- Resolución automática de comuna: Nominatim → `/api/comunas/resolve` → código SII
- Búsqueda por rol directo: escribir `15103-12-45` busca por PK (~1ms)
- Ranking por relevancia con `similarity()` de pg_trgm
- Click/drag en mapa → reverse geocoding → búsqueda
- Normalización: strip "Avenida", "Presidente", etc. (SII los abrevia)
- Cascada de fallback texto (solo pág 1): con comuna → sin número → sin comuna

**2. Por rol SII (RolSearch):** formulario guiado
- Dropdown Región → Dropdown Comuna (filtrada) → Manzana → Predio
- Navega directo a `/predio/:c/:m/:p`

### Visualización 3D del Edificio (Experimental)
- Canvas isométrico puro (sin dependencias 3D)
- Clasificación de unidades por **código de destino SII** (Z=Estacionamiento, L=Bodega, H=Habitacional, C=Comercio, O=Oficina)
- Estacionamientos y bodegas como **data anexa** (tarjetas informativas), no como pisos
- Pisos inferidos del número de unidad (DP 301 → piso 3)
- Color por tipo: lime=deptos, ámbar=locales, azul=oficinas, rosa=tu unidad
- Texturas por materialidad: B=hormigón (líneas), C=albañilería (ladrillos), E=madera (vetas), A/G=acero (cross-hatch), F=adobe (bloques)
- Hover muestra detalle por piso

### Códigos SII (estructura_detalle_catastral.pdf)

**Destinos:** A=Agrícola, B=Agroindustrial, C=Comercio, D=Deporte, E=Educación,
F=Forestal, G=Hotel, H=Habitacional, I=Industria, L=Bodega, M=Minería, O=Oficina,
P=Admin Pública, Q=Culto, S=Salud, T=Transporte, V=Otros, W=Sitio Eriazo,
Y=Gallineros, Z=Estacionamiento

**Materiales:** A=Acero, B=Hormigón, C=Albañilería, E=Madera, F=Adobe,
G=Perfiles Metálicos, K=Prefabricado. Compuestos: GA/GB/GC/GE/GL/GF (galpones),
OA/OB/OE (obras), SA/SB (silos), EA/EB (estanques), M (marquesina),
P (pavimento), W (piscina), TA/TE/TL (techumbres)

**Calidad:** 1=Superior, 2=Media Superior, 3=Media, 4=Media Inferior, 5=Inferior

**Condición Especial:** AL=Altillo, CA=Construcción Abierta, CI=Construcción Interior,
MS=Mansarda, PZ=Posi Zócalo, SB=Subterráneo, TM=Catástrofe 2010

### Design System
- Dark mode (#0a0a0a), acento lime green (#bafb00)
- Font: Inter (Google Fonts)
- Glassmorphism en header

---

## Deploy

### Servicios

| Servicio | Tipo | Detalle |
|----------|------|---------|
| `roles-db` | Docker container | PostgreSQL 16, puerto 5435 |
| `roles-api` | systemd service | uvicorn, 2 workers, puerto 3009 |
| Nginx | sistema | SSL + proxy /api/ + SPA fallback |

### Comandos útiles

```bash
# Backend
systemctl restart roles-api
systemctl status roles-api
journalctl -u roles-api -f

# Database
docker exec -it roles-db psql -U roles_app -d roles
docker compose -f /var/www/roles.tremen.tech/docker-compose.yml up -d

# Frontend (desde máquina local en roles-frontend/)
npm run build
scp -r dist/* root@46.224.221.33:/var/www/roles.tremen.tech/frontend/

# Pipeline (actualizar datos)
cd /var/www/roles.tremen.tech/pipeline
/var/www/roles.tremen.tech/.venv/bin/python 05_run_all.py

# SSL
certbot renew
```

### Nginx config
```
/etc/nginx/sites-available/roles.tremen.tech
  → symlink en /etc/nginx/sites-enabled/
  → /api/* proxy_pass http://127.0.0.1:3009
  → /* try_files SPA fallback
  → SSL Let's Encrypt (auto-renewal)
```

---

## Datos S3

**Bucket:** `siipredios` (Hetzner Object Storage, endpoint `nbg1.your-objectstorage.com`)
**Credenciales:** en pipeline/config.py y backend/routers/descargas.py

| Prefijo | Contenido |
|---------|-----------|
| `catastro_historico/output/` | 16 CSVs procesados (22.8 GB) |
| `catastro_historico/{periodo}/` | Archivos crudos SII (BRORGA + BRTMPNACROL) |
| `2025ss/` | CSVs + GeoJSON por comuna (para predios.tremen.tech) |
| `2025ss_bcn/` | TIFs por comuna |
| `IPT_Chile/` | GeoJSON instrumentos de planificación territorial |

---


---

## Seguridad

### Secretos y credenciales

Todos los secretos están en `/var/www/roles.tremen.tech/.env` (chmod 600, propiedad de `roles-api`).
**Nunca** hardcodear credenciales en código fuente. Los archivos `.py` usan `os.environ[]` sin fallbacks.

| Variable | Descripción |
|----------|-------------|
| `DB_USER`, `DB_PASS` | Usuario PostgreSQL limitado (`roles_reader`, solo SELECT) |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Hetzner Object Storage |
| `HERE_API_KEY` | HERE Geocoding API |
| `STATS_TOKEN` | Token para `/api/geocode/stats` |

El systemd service carga las variables via `EnvironmentFile=/var/www/roles.tremen.tech/.env`.

### Base de datos

- **Usuario de aplicación:** `roles_reader` — solo permisos `SELECT` en las tablas. Sin superuser, sin createdb, sin createrole.
- **Usuario admin:** `roles_app` — superuser, solo para migraciones y pipeline. No usado por la API.
- **Puerto:** `127.0.0.1:5435` (loopback only). Postgres además tiene `listen_addresses=localhost`.

### Proceso de la API

- **Usuario OS:** `roles-api` (sin privilegios, sin shell, sin home)
- **Uvicorn:** `--proxy-headers --forwarded-allow-ips 127.0.0.1` — confía solo en Nginx para IP real del cliente
- **Docs deshabilitados:** `/docs`, `/redoc`, `/openapi.json` retornan 404 en producción

### Rate limiting

| Capa | Límite | Scope |
|------|--------|-------|
| Nginx `limit_req_zone` | 30 req/min, burst 20 | Todos los endpoints `/api/*`, por IP |
| Geocoding por minuto | 10 req/min | `/api/geocode`, `/api/revgeocode`, por IP |
| Geocoding diario | 200 req/día | Por IP |
| Geocoding mensual global | 25,000 req/mes | Todos los usuarios (margen de 5K sobre los 30K gratis de HERE) |
| Descargas S3 | 10 presigned URLs/hora | `/api/descargas/{id}/url`, por IP |

El rate limiting de geocoding usa estado compartido entre workers via `/tmp/geocode_state.json` (thread-safe con lock).
La IP del cliente se obtiene de `request.client.host` (configurado por uvicorn proxy-headers), no de `X-Forwarded-For` (no spoofable).

### Geocoding proxy

La API key de HERE **nunca** llega al cliente. El frontend llama a `/api/geocode` y `/api/revgeocode` que proxean a HERE desde el backend.
Cache bounded (max 2000 entries, LRU eviction, TTL 1 hora) para reducir llamadas a HERE.
Errores de HERE se logean con `logger.error()` y retornan 502 al cliente.

### Firewall (UFW)

```
Status: active
Default: deny incoming

22/tcp    ALLOW   (SSH — protegido por fail2ban)
80/tcp    ALLOW   (HTTP → redirect HTTPS)
443/tcp   ALLOW   (HTTPS)
3000:3100/tcp ALLOW (otros servicios)
8081/tcp  ALLOW   (otros servicios)
8082/tcp  ALLOW   (otros servicios)
```

### SSH

- fail2ban activo: max 5 intentos fallidos → ban 1 hora
- Puerto 22 (estándar)

### Nginx — Headers de seguridad

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(self), camera=(), microphone=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' [gtag]; style-src 'self' 'unsafe-inline' [fonts]; font-src 'self' [gstatic]; img-src 'self' data: [carto] [unpkg]; connect-src 'self' [analytics]
```

Configuración en `/etc/nginx/snippets/security-headers.conf`, incluida en el server block.

### CORS

- Origins: solo `https://roles.tremen.tech` y `http://localhost:5173` (desarrollo)
- Métodos: solo `GET`
- Headers: solo `Content-Type`, `Accept`

### Docker

- Container `roles-db`: limits `memory: 8G`, `cpus: 4`
- Puerto solo en loopback: `127.0.0.1:5435:5432`
- Postgres: `listen_addresses=localhost`

### Logging

- FastAPI: formato estructurado (`%(asctime)s %(levelname)s %(name)s %(message)s`) via journalctl
- Nginx: access log + error log estándar
- Geocoding: errores de HERE logueados explícitamente
- fail2ban: log de baneos SSH

### Checklist de rotación de secretos

Al rotar credenciales:
1. Actualizar `/var/www/roles.tremen.tech/.env`
2. `systemctl restart roles-api`
3. Si es DB: actualizar password en PostgreSQL con `ALTER ROLE`
4. Si es S3: actualizar en Hetzner Cloud Console
5. Si es HERE: actualizar en HERE Developer Portal

## Pipeline de actualización semestral

Cuando el SII publica nuevos datos (cada 6 meses):

1. Subir el nuevo CSV procesado a `s3://siipredios/catastro_historico/output/catastro_{YYYY_S}.csv`
2. Actualizar `PERIODS` en pipeline/config.py
3. Ejecutar: `/var/www/roles.tremen.tech/.venv/bin/python 05_run_all.py`
4. Actualizar `FILE_SIZES` y `ROW_COUNTS` en backend/routers/descargas.py
5. Reiniciar: `systemctl restart roles-api`
