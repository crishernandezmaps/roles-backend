# Contribuir a roles.tremen.tech

## Sobre el proyecto

Este es el backend + pipeline del [Explorador Catastral SII](https://roles.tremen.tech). El frontend está en [roles-frontend](https://github.com/crishernandezmaps/roles-frontend). Ambos repos son copias sanitizadas del código en producción — sin credenciales, sin datos, sin IPs internas.

---

## Para colaboradores externos

### Cómo contribuir

1. Haz fork del repo
2. Crea una rama descriptiva (`fix/nearby-radius`, `feat/export-geojson`)
3. Haz tus cambios y prueba localmente
4. Abre un Pull Request con descripción clara de qué cambia y por qué

### Desarrollo local

```bash
git clone https://github.com/crishernandezmaps/roles-backend.git
cd roles-backend
cp .env.example .env
# Edita .env con tus credenciales

docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn psycopg_pool psycopg[binary] httpx boto3

# Cargar schema
docker exec -i roles-db psql -U roles_app -d roles < pipeline/sql/schema.sql

# Levantar API
cd backend && uvicorn main:app --host 0.0.0.0 --port 3009 --reload
```

### Qué aceptamos

- Bug fixes con descripción del problema
- Nuevos endpoints con caso de uso claro
- Optimizaciones de queries con EXPLAIN ANALYZE
- Mejoras al pipeline de ingesta

### Qué NO aceptamos

- Cambios que expongan credenciales o datos internos
- Dependencias pesadas innecesarias
- Endpoints que permitan escritura (la API es solo lectura)
- Cambios que rompan la estructura de los CSVs del SII

---

## Para Claude Code — Workflow de mantenimiento

### Arquitectura de repos

| Repo | Contenido | Directorio local | Directorio VPS |
|------|-----------|-------------------|----------------|
| `roles-frontend` | React SPA | `/Users/newmarkchile/Documents/TREMEN/5_PROJECTS/prediosChile/roles-frontend/` | `/var/www/roles.tremen.tech/frontend/` (solo `dist/`) |
| `roles-backend` | FastAPI + Pipeline | Copia sanitizada en `/tmp/roles-backend/` | `/var/www/roles.tremen.tech/backend/` + `pipeline/` |

### VPS

- **IP:** `46.224.221.33`
- **SSH:** `ssh -o StrictHostKeyChecking=no root@46.224.221.33`
- **Proyecto:** `/var/www/roles.tremen.tech/`

### Commit en roles-frontend

El código fuente está local. Se edita directamente y se commitea:

```bash
cd /Users/newmarkchile/Documents/TREMEN/5_PROJECTS/prediosChile/roles-frontend
git add <archivos>
git commit -m "mensaje"
git push
```

### Deploy de roles-frontend

```bash
npm run build
scp -o StrictHostKeyChecking=no -r dist/* root@46.224.221.33:/var/www/roles.tremen.tech/frontend/
```

No requiere reiniciar ningún servicio — Nginx sirve los archivos estáticos directamente.

### Commit en roles-backend

El código en producción está en la VPS. El repo público es una **copia sanitizada**. El workflow es:

1. **Editar en la VPS** — el código real se modifica directamente en `/var/www/roles.tremen.tech/`
2. **Probar en producción** — `systemctl restart roles-api`
3. **Sincronizar al repo público** — copiar los archivos modificados a `/tmp/roles-backend/`, sanitizar secrets si es necesario, commitear y pushear

```bash
# Copiar archivo modificado desde VPS
scp -o StrictHostKeyChecking=no root@46.224.221.33:/var/www/roles.tremen.tech/backend/routers/predios.py /tmp/roles-backend/backend/routers/

# Verificar que no tenga secrets
grep -rn 'password\|secret\|api_key\|r0les\|PNGG\|uAYh' /tmp/roles-backend/

# Commitear
cd /tmp/roles-backend
git add -A
git commit -m "mensaje"
git push
```

### Sanitización obligatoria

Antes de cualquier push a los repos públicos, SIEMPRE ejecutar:

```bash
grep -rn 'r0les_\|PNGG5\|uAYhy\|rolesReader\|Tr3m3n\|46\.224\.221\.33' /tmp/roles-backend/
```

Si hay matches, sanitizar antes de commitear. Los secrets deben estar SOLO en:
- `.env` en la VPS (nunca en el repo)
- `os.environ[]` en el código (sin fallbacks hardcodeados)

### Archivos que NUNCA deben tener secrets

| Archivo | Debe usar |
|---------|-----------|
| `pipeline/config.py` | `os.environ["VAR"]` |
| `backend/config.py` | `os.environ["VAR"]` |
| `backend/routers/descargas.py` | `os.environ["VAR"]` |
| `backend/routers/geocode.py` | `os.environ["VAR"]` |
| `docker-compose.yml` | `${VAR}` desde `.env` |

### Convenciones de commit

- Mensajes en inglés, concisos, en imperativo ("Add filter", "Fix pagination", no "Added" ni "Fixes")
- Primera línea: qué cambia (max 72 chars)
- Cuerpo opcional: por qué
- Siempre incluir co-author:

```
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

### Reinicio de servicios en VPS

```bash
# Backend (después de cambios en backend/)
ssh root@46.224.221.33 "systemctl restart roles-api"

# Base de datos (raro, solo si cambia docker-compose.yml)
ssh root@46.224.221.33 "cd /var/www/roles.tremen.tech && docker compose up -d"

# Nginx (después de cambios en CSP, rate limiting, headers)
ssh root@46.224.221.33 "nginx -t && systemctl reload nginx"
```

---

## Licencia

MIT
