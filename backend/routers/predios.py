import re
from fastapi import APIRouter, Query
from db import pool
from typing import Optional
from decimal import Decimal

router = APIRouter()

SUP_EXPR = "COALESCE(NULLIF(a.dc_sup_terreno, 0), a.sup_construida_total)"

ROL_PATTERN = re.compile(r'^(\d{1,5})-(\d{1,4})-(\d{1,5})$')

# SII doesn't use these prefixes
STREET_PREFIXES = re.compile(
    r'^(AVENIDA|AV\.?|CALLE|PASAJE|PSJE\.?|PJE\.?|CAMINO|RUTA|AUTOPISTA|'
    r'BOULEVARD|BVD\.?|COSTANERA|DIAGONAL|GRAN|CIRCUNVALACION)\s+',
    re.IGNORECASE
)

# Title/rank words the SII abbreviates — strip for matching
TITLE_WORDS = re.compile(
    r'\b(PRESIDENTE|GENERAL|CORONEL|CAPITAN|TENIENTE|SARGENTO|ALMIRANTE|'
    r'DOCTOR|DOCTORA|PROFESOR|PROFESORA|LIBERTADOR|BERNARDO|'
    r'SANTO|SANTA|COMANDANTE|BRIGADIER|MARISCAL|OBISPO|MONSENOR|'
    r'CARDENAL|PADRE|MADRE|FRAY|SOR|HERMANO|'
    r'LATERAL|PONIENTE|ORIENTE|NORTE|SUR)\b',
    re.IGNORECASE
)

def normalize_address(raw):
    """Clean address for better SII matching."""
    s = raw.strip().upper()
    s = STREET_PREFIXES.sub('', s)
    s = TITLE_WORDS.sub('', s)
    s = re.sub(r'\s+', ' ', s).strip()
    words = s.split()
    if not words:
        return None
    return '%'.join(words)


@router.get("/comunas/resolve")
def resolve_comuna(nombre: str = Query(...)):
    """Map a comuna name (from Nominatim) to its SII code."""
    clean = nombre.strip()
    with pool.connection() as conn:
        # Exact match first
        cur = conn.execute(
            "SELECT codigo, nombre FROM comunas_lookup WHERE LOWER(nombre) = LOWER(%s) LIMIT 1",
            [clean]
        )
        row = cur.fetchone()
        if row:
            return {"codigo": row[0], "nombre": row[1]}
        # Fuzzy fallback
        cur = conn.execute(
            "SELECT codigo, nombre, similarity(LOWER(nombre), LOWER(%s)) as sim FROM comunas_lookup WHERE similarity(LOWER(nombre), LOWER(%s)) > 0.3 ORDER BY sim DESC LIMIT 1",
            [clean, clean]
        )
        row = cur.fetchone()
        if row:
            return {"codigo": row[0], "nombre": row[1]}
        return {"codigo": None, "nombre": None}


@router.get("/predios/autocomplete")
def autocomplete_predios(
    q: str = Query(..., min_length=3),
    comuna: Optional[int] = None,
    limit: int = Query(8, ge=1, le=20),
):
    """Typeahead suggestions from actual SII addresses."""
    cleaned = normalize_address(q)
    if not cleaned:
        return []

    conditions = ["a.rc_direccion IS NOT NULL"]
    params = []

    if comuna:
        conditions.append("a.comuna = %s")
        params.append(comuna)

    # Use ILIKE for matching
    conditions.append("a.rc_direccion ILIKE %s")
    params.append(f"%{cleaned}%")

    where = "WHERE " + " AND ".join(conditions)

    # For ordering by similarity we need the raw search term
    raw_upper = q.strip().upper()

    with pool.connection() as conn:
        cur = conn.execute(
            f"""SELECT DISTINCT ON (a.rc_direccion) a.rc_direccion, a.comuna,
                       c.nombre as comuna_nombre,
                       similarity(a.rc_direccion, %s) as sim
                FROM catastro_actual a
                LEFT JOIN comunas_lookup c ON c.codigo = a.comuna
                {where}
                ORDER BY a.rc_direccion, sim DESC
                LIMIT %s""",
            [raw_upper] + params + [limit],
        )
        results = [{"direccion": r[0], "comuna": r[1], "comuna_nombre": r[2], "score": round(float(r[3]), 3)} for r in cur.fetchall()]

    # Re-sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


@router.get("/predios")
def search_predios(
    comuna: Optional[int] = None,
    direccion: Optional[str] = None,
    destino: Optional[str] = None,
    sup_min: Optional[float] = None,
    sup_max: Optional[float] = None,
    avaluo_min: Optional[int] = None,
    avaluo_max: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
):
    conditions = []
    params = []
    use_similarity_order = False
    similarity_term = None

    # Detect direct rol search (e.g., "15103-12-45")
    if direccion:
        m = ROL_PATTERN.match(direccion.strip())
        if m:
            c, mz, pr = int(m.group(1)), int(m.group(2)), int(m.group(3))
            conditions.append("a.comuna = %s")
            params.append(c)
            conditions.append("a.manzana = %s")
            params.append(mz)
            conditions.append("a.predio = %s")
            params.append(pr)
            direccion = None  # skip ILIKE

    if comuna is not None:
        conditions.append("a.comuna = %s")
        params.append(comuna)
    if direccion:
        cleaned = normalize_address(direccion)
        if cleaned:
            conditions.append("a.rc_direccion ILIKE %s")
            params.append(f"%{cleaned}%")
            use_similarity_order = True
            similarity_term = cleaned.replace('%', ' ')
    if destino:
        conditions.append("a.dc_cod_destino = %s")
        params.append(destino)
    if sup_min is not None:
        conditions.append(f"{SUP_EXPR} >= %s")
        params.append(sup_min)
    if sup_max is not None:
        conditions.append(f"{SUP_EXPR} <= %s")
        params.append(sup_max)
    if avaluo_min is not None:
        conditions.append("a.rc_avaluo_total >= %s")
        params.append(avaluo_min)
    if avaluo_max is not None:
        conditions.append("a.rc_avaluo_total <= %s")
        params.append(avaluo_max)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * limit

    if use_similarity_order:
        order_clause = "ORDER BY similarity(a.rc_direccion, %s) DESC, a.comuna, a.manzana, a.predio"
        order_params = [similarity_term]
    else:
        order_clause = "ORDER BY a.comuna, a.manzana, a.predio"
        order_params = []

    with pool.connection() as conn:
        cur = conn.execute(f"SELECT count(*) FROM catastro_actual a {where}", params)
        total = cur.fetchone()[0]

        cur = conn.execute(
            f"""SELECT a.comuna, a.manzana, a.predio,
                       a.rc_direccion, a.dc_cod_destino,
                       a.dc_sup_terreno, a.sup_construida_total,
                       {SUP_EXPR} as superficie,
                       a.rc_avaluo_total,
                       a.rc_cod_ubicacion,
                       c.nombre as comuna_nombre, c.region
                FROM catastro_actual a
                LEFT JOIN comunas_lookup c ON c.codigo = a.comuna
                {where}
                {order_clause}
                LIMIT %s OFFSET %s""",
            params + order_params + [limit, offset],
        )
        data = []
        for r in cur.fetchall():
            data.append({
                "comuna": r[0], "manzana": r[1], "predio": r[2],
                "rc_direccion": r[3], "dc_cod_destino": r[4],
                "dc_sup_terreno": _f(r[5]),
                "sup_construida_total": _f(r[6]),
                "superficie": _f(r[7]),
                "rc_avaluo_total": r[8],
                "rc_cod_ubicacion": r[9],
                "comuna_nombre": r[10], "region": r[11],
            })

    return {
        "data": data,
        "pagination": {
            "page": page, "limit": limit, "total": total,
            "pages": (total + limit - 1) // limit if limit else 0,
        },
    }


@router.get("/predios/{comuna}/{manzana}/{predio}")
def get_predio(comuna: int, manzana: int, predio: int):
    with pool.connection() as conn:
        cur = conn.execute(
            f"""SELECT a.*,
                       {SUP_EXPR} as superficie,
                       c.nombre as comuna_nombre, c.region
               FROM catastro_actual a
               LEFT JOIN comunas_lookup c ON c.codigo = a.comuna
               WHERE a.comuna = %s AND a.manzana = %s AND a.predio = %s""",
            [comuna, manzana, predio],
        )
        r = cur.fetchone()
        if not r:
            return {"error": "Predio no encontrado"}
        cols = [desc.name for desc in cur.description]
        return {k: _f(v) if isinstance(v, Decimal) else v for k, v in zip(cols, r)}


@router.get("/predios/{comuna}/{manzana}/{predio}/evolucion")
def get_evolucion(comuna: int, manzana: int, predio: int):
    with pool.connection() as conn:
        cur = conn.execute(
            """SELECT anio, semestre, rc_avaluo_total, rc_avaluo_exento,
                      rc_cuota_trimestral, dc_avaluo_fiscal,
                      dc_contribucion_semestral, dc_sup_terreno,
                      sup_construida_total, dc_cod_destino
               FROM catastro_historico
               WHERE comuna = %s AND manzana = %s AND predio = %s
               ORDER BY anio, semestre""",
            [comuna, manzana, predio],
        )
        data = [
            {
                "periodo": f"{r[0]}S{r[1]}",
                "anio": r[0], "semestre": r[1],
                "rc_avaluo_total": r[2], "rc_avaluo_exento": r[3],
                "rc_cuota_trimestral": r[4], "dc_avaluo_fiscal": r[5],
                "dc_contribucion_semestral": r[6],
                "dc_sup_terreno": _f(r[7]),
                "sup_construida_total": _f(r[8]),
                "dc_cod_destino": r[9],
            }
            for r in cur.fetchall()
        ]
    return {"comuna": comuna, "manzana": manzana, "predio": predio, "evolucion": data}


@router.get("/predios/{comuna}/{manzana}/{predio}/edificio")
def get_edificio(comuna: int, manzana: int, predio: int):
    """Get building context if this predio is part of a building (has bien comun)."""
    with pool.connection() as conn:
        cur = conn.execute(
            "SELECT dc_bc1_comuna, dc_bc1_manzana, dc_bc1_predio FROM catastro_actual WHERE comuna = %s AND manzana = %s AND predio = %s",
            [comuna, manzana, predio]
        )
        row = cur.fetchone()
        if not row or not row[2] or row[2] == 0:
            return {"es_edificio": False}

        bc_comuna, bc_manzana, bc_predio = row

        cur = conn.execute(
            """SELECT count(*) as unidades,
                      round(sum(sup_construida_total)::numeric, 0) as m2_total,
                      round(avg(sup_construida_total)::numeric, 1) as avg_m2,
                      min(sup_construida_total) as min_m2,
                      max(sup_construida_total) as max_m2,
                      round(avg(rc_avaluo_total)) as avg_avaluo,
                      min(rc_avaluo_total) as min_avaluo,
                      max(rc_avaluo_total) as max_avaluo,
                      round(avg(dc_contribucion_semestral)) as avg_contrib,
                      count(CASE WHEN dc_cod_destino = 'H' THEN 1 END) as habitacional,
                      count(CASE WHEN dc_cod_destino = 'C' THEN 1 END) as comercial,
                      count(CASE WHEN dc_cod_destino NOT IN ('H','C') THEN 1 END) as otros
               FROM catastro_actual
               WHERE comuna = %s AND manzana = %s AND dc_bc1_predio = %s""",
            [bc_comuna, bc_manzana, bc_predio]
        )
        stats = cur.fetchone()

        cur = conn.execute(
            """SELECT predio, rc_direccion, sup_construida_total, rc_avaluo_total
               FROM catastro_actual
               WHERE comuna = %s AND manzana = %s AND dc_bc1_predio = %s
               ORDER BY predio LIMIT 10""",
            [bc_comuna, bc_manzana, bc_predio]
        )
        sample = [{"predio": r[0], "direccion": r[1], "m2": _f(r[2]), "avaluo": r[3]} for r in cur.fetchall()]

        return {
            "es_edificio": True,
            "bien_comun": f"{bc_comuna}-{bc_manzana}-{bc_predio}",
            "unidades": stats[0],
            "m2_total": _f(stats[1]),
            "avg_m2": _f(stats[2]),
            "min_m2": _f(stats[3]),
            "max_m2": _f(stats[4]),
            "avg_avaluo": _f(stats[5]),
            "min_avaluo": stats[6],
            "max_avaluo": stats[7],
            "avg_contrib": _f(stats[8]),
            "habitacional": stats[9],
            "comercial": stats[10],
            "otros": stats[11],
            "muestra": sample,
        }


@router.get("/comunas")
def list_comunas():
    with pool.connection() as conn:
        cur = conn.execute("SELECT codigo, nombre, region FROM comunas_lookup ORDER BY region, nombre")
        return [{"codigo": r[0], "nombre": r[1], "region": r[2]} for r in cur.fetchall()]


@router.get("/destinos")
def list_destinos():
    with pool.connection() as conn:
        cur = conn.execute("SELECT DISTINCT dc_cod_destino FROM catastro_actual WHERE dc_cod_destino IS NOT NULL ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def _f(v):
    if v is None: return None
    if isinstance(v, Decimal): return float(v)
    return v


@router.get("/predios/{comuna}/{manzana}/{predio}/edificio3d")
def get_edificio_3d(comuna: int, manzana: int, predio: int):
    """Get building data structured for 3D visualization."""
    with pool.connection() as conn:
        cur = conn.execute(
            "SELECT dc_bc1_predio, pisos_max FROM catastro_actual WHERE comuna = %s AND manzana = %s AND predio = %s",
            [comuna, manzana, predio]
        )
        row = cur.fetchone()
        if not row or not row[0] or row[0] == 0:
            return {"es_edificio": False}

        bc_predio = row[0]
        pisos_max = row[1] or 1

        cur = conn.execute(
            """SELECT predio, rc_direccion, sup_construida_total, rc_avaluo_total,
                      dc_cod_destino, pisos_max, materiales, calidades
               FROM catastro_actual
               WHERE comuna = %s AND manzana = %s AND dc_bc1_predio = %s
               ORDER BY predio""",
            [comuna, manzana, bc_predio]
        )

        def classify_unit(direccion, destino):
            """Classify unit type using SII destino code (primary) and address prefix (secondary).
            Destino codes: Z=Estacionamiento, L=Bodega, H=Habitacional, C=Comercio, O=Oficina,
            D=Deporte, E=Educacion, G=Hotel, I=Industria, M=Mineria, P=Admin publica,
            Q=Culto, S=Salud, T=Transporte, V=Otros, W=Sitio eriazo
            """
            if destino == "Z":
                return "estacionamiento"
            if destino == "L":
                return "bodega"
            if destino == "O":
                return "oficina"
            d = direccion.upper()
            if destino == "H":
                if re.search(r"CS\s*\d", d):
                    return "casa"
                return "departamento"
            if destino == "C":
                if re.search(r"(OF|OFC)\s*\d", d):
                    return "oficina"
                return "local"
            return "otro"

        def infer_floor(direccion, tipo):
            """Infer floor number from unit number in address."""
            if tipo in ("estacionamiento", "bodega"):
                return -1
            match = re.search(r"(?:DP|DEP|DPTO|DEPTO|OF|OFC|CS|DX|DS|PH|PS|D)\s+(\d+)", direccion, re.I)
            if match:
                unit_num = match.group(1)
                if len(unit_num) >= 2:
                    floor = int(unit_num[0])
                    return floor if floor > 0 else 1
                return 1
            return 0

        units = []
        annexes = []
        floors = {}
        total_m2 = 0
        annex_m2 = 0
        for r in cur.fetchall():
            unit_predio = r[0]
            direccion = r[1] or ''
            m2 = float(r[2]) if r[2] else 0
            avaluo = r[3] or 0
            destino = r[4] or 'H'
            pisos = r[5] or 1
            material = r[6] or ""
            calidad = r[7] or ""
            total_m2 += m2

            tipo = classify_unit(direccion, destino)
            floor = infer_floor(direccion, tipo)

            unit = {
                "predio": unit_predio,
                "direccion": direccion,
                "m2": m2,
                "avaluo": avaluo,
                "destino": destino,
                "piso": floor,
                "es_actual": unit_predio == int(predio),
                "tipo": tipo,
                "material": material,
                "calidad": calidad,
            }

            if tipo in ('estacionamiento', 'bodega'):
                annexes.append(unit)
                annex_m2 += m2
            else:
                units.append(unit)

            if floor not in floors:
                floors[floor] = {"piso": floor, "unidades": 0, "m2": 0, "tipos": {}}
            floors[floor]["unidades"] += 1
            floors[floor]["m2"] += m2
            floors[floor]["tipos"][tipo] = floors[floor]["tipos"].get(tipo, 0) + 1

        # Estimate footprint (exclude annexes)
        building_m2 = total_m2 - annex_m2
        footprint_m2 = building_m2 / max(pisos_max, 1) if pisos_max > 0 else building_m2
        side = footprint_m2 ** 0.5

        # Annex summary
        annex_summary = {}
        for a in annexes:
            t = a["tipo"]
            if t not in annex_summary:
                annex_summary[t] = {"count": 0, "m2": 0, "avg_avaluo": 0, "total_avaluo": 0}
            annex_summary[t]["count"] += 1
            annex_summary[t]["m2"] += a["m2"]
            annex_summary[t]["total_avaluo"] += a["avaluo"]
        for t in annex_summary:
            s = annex_summary[t]
            s["m2"] = round(s["m2"], 0)
            s["avg_avaluo"] = round(s["total_avaluo"] / s["count"]) if s["count"] else 0

        return {
            "es_edificio": True,
            "pisos_max": pisos_max,
            "total_unidades": len(units) + len(annexes),
            "total_m2": round(total_m2, 0),
            "footprint_m2": round(footprint_m2, 0),
            "side_estimate": round(side, 1),
            "material_dominante": max(set(u["material"] for u in units if u["material"]), key=lambda m: sum(1 for u in units if u["material"] == m), default="") if units else "",
            "pisos": sorted([v for v in floors.values() if v["piso"] >= 0], key=lambda x: x["piso"]),
            "unidades": units,
            "anexos": annexes,
            "anexo_resumen": annex_summary,
        }


@router.get("/predios/nearby")
def search_predios_nearby(
    lat: float = Query(...),
    lon: float = Query(...),
    direccion: Optional[str] = None,
    radius: int = Query(300, ge=10, le=1000),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
):
    """Search predios near a coordinate. If direccion is provided, text-matching
    results are boosted to the top, followed by remaining nearby predios."""
    offset = (page - 1) * limit
    point_sql = "geography(ST_SetSRID(ST_MakePoint(%s, %s), 4326))"

    # Normalize address for text matching
    addr_pattern = None
    if direccion:
        cleaned = normalize_address(direccion)
        if cleaned:
            addr_pattern = f"%{cleaned}%"

    # Build ORDER BY: text similarity boost first, then distance
    # Tier 0: high similarity (fuzzy/vector match, e.g. "FRANCIA 5970" ≈ "FRANCIA 5970")
    # Tier 1: partial ILIKE match (e.g. "FRANCIA" matches "FRANCIA 5774")
    # Tier 2: no text match, ordered by distance only
    if addr_pattern:
        similarity_term = direccion.strip().upper()
        order_clause = f"""ORDER BY
            CASE
              WHEN similarity(a.rc_direccion, %s) > 0.5 THEN 0
              WHEN a.rc_direccion ILIKE %s THEN 1
              ELSE 2
            END,
            CASE a.dc_cod_destino
              WHEN 'H' THEN 0 WHEN 'O' THEN 0
              WHEN 'C' THEN 1 WHEN 'E' THEN 1 WHEN 'S' THEN 1
              WHEN 'Z' THEN 3 WHEN 'L' THEN 3
              ELSE 2
            END,
            similarity(a.rc_direccion, %s) DESC,
            a.rc_direccion ASC"""
        order_params = [similarity_term, addr_pattern, similarity_term]
    else:
        order_clause = f"""ORDER BY
            CASE a.dc_cod_destino
              WHEN 'H' THEN 0 WHEN 'O' THEN 0
              WHEN 'C' THEN 1 WHEN 'E' THEN 1 WHEN 'S' THEN 1
              WHEN 'Z' THEN 3 WHEN 'L' THEN 3
              ELSE 2
            END,
            ST_Distance(geography(ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326)),
                        {point_sql}, false)"""
        order_params = [lon, lat]

    with pool.connection() as conn:
        cur = conn.execute(
            f"SELECT count(*) FROM catastro_actual a "
            f"WHERE a.lat IS NOT NULL AND ST_DWithin("
            f"geography(ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326)), "
            f"{point_sql}, %s)",
            [lon, lat, radius],
        )
        total = cur.fetchone()[0]

        cur = conn.execute(
            f"""SELECT a.comuna, a.manzana, a.predio,
                       a.rc_direccion, a.dc_cod_destino,
                       a.dc_sup_terreno, a.sup_construida_total,
                       {SUP_EXPR} as superficie,
                       a.rc_avaluo_total,
                       a.rc_cod_ubicacion,
                       c.nombre as comuna_nombre, c.region,
                       a.lat as predio_lat, a.lon as predio_lon,
                       ST_Distance(
                         geography(ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326)),
                         {point_sql}, false
                       ) as distancia_m
                FROM catastro_actual a
                LEFT JOIN comunas_lookup c ON c.codigo = a.comuna
                WHERE a.lat IS NOT NULL
                  AND ST_DWithin(
                    geography(ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326)),
                    {point_sql}, %s
                  )
                {order_clause}
                LIMIT %s OFFSET %s""",
            [lon, lat, lon, lat, radius] + order_params + [limit, offset],
        )
        data = []
        for row in cur.fetchall():
            data.append({
                "comuna": row[0], "manzana": row[1], "predio": row[2],
                "rc_direccion": row[3], "dc_cod_destino": row[4],
                "dc_sup_terreno": _f(row[5]),
                "sup_construida_total": _f(row[6]),
                "superficie": _f(row[7]),
                "rc_avaluo_total": row[8],
                "rc_cod_ubicacion": row[9],
                "comuna_nombre": row[10], "region": row[11],
                "lat": row[12], "lon": row[13],
                "distancia_m": round(row[14], 1) if row[14] is not None else None,
            })

    return {
        "data": data,
        "pagination": {
            "page": page, "limit": limit, "total": total,
            "pages": (total + limit - 1) // limit if limit else 0,
        },
        "radius_used": radius,
        "coordinates": {"lat": lat, "lon": lon},
    }

@router.get("/predios/nearby/markers")
def nearby_markers(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: int = Query(300, ge=10, le=500),
):
    """Return lightweight marker data for all predios in radius (max 500)."""
    point_sql = "geography(ST_SetSRID(ST_MakePoint(%s, %s), 4326))"
    with pool.connection() as conn:
        cur = conn.execute(
            f"""SELECT a.comuna, a.manzana, a.predio,
                       a.rc_direccion, a.dc_cod_destino, a.lat, a.lon
                FROM catastro_actual a
                WHERE a.lat IS NOT NULL
                  AND ST_DWithin(
                    geography(ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326)),
                    {point_sql}, %s
                  )
                ORDER BY ST_Distance(
                    geography(ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326)),
                    {point_sql}, false
                )
                LIMIT 500""",
            [lon, lat, radius, lon, lat],
        )
        return [
            {"c": r[0], "m": r[1], "p": r[2], "d": r[3], "t": r[4], "lat": r[5], "lon": r[6]}
            for r in cur.fetchall()
        ]

