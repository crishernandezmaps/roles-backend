from fastapi import APIRouter
from db import pool
from decimal import Decimal

router = APIRouter()

def _n(v):
    if v is None: return None
    if isinstance(v, Decimal): return float(v)
    return v

DESTINO_LABELS = {
    'H': 'Habitacional', 'C': 'Comercial', 'I': 'Industrial',
    'O': 'Oficina', 'E': 'Educación', 'S': 'Salud',
    'A': 'Agrícola', 'F': 'Forestal', 'M': 'Minería',
    'D': 'Deportes', 'G': 'Estacionamiento', 'T': 'Transporte',
    'B': 'Bodega', 'L': 'Hotel/Motel', 'Z': 'Otros',
}


@router.get("/estadisticas/resumen")
def stats_resumen():
    with pool.connection() as conn:
        cur = conn.execute("""
            SELECT 
                count(*) as total_predios,
                count(DISTINCT comuna) as total_comunas,
                round(avg(rc_avaluo_total)) as avg_avaluo,
                round(sum(rc_avaluo_total)::numeric / 1e12, 2) as total_avaluo_trillones,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY rc_avaluo_total) as mediana_avaluo,
                round(avg(COALESCE(NULLIF(dc_sup_terreno, 0), sup_construida_total))::numeric, 1) as avg_superficie,
                round(sum(dc_contribucion_semestral)::numeric / 1e9, 1) as total_contrib_billones
            FROM catastro_actual
        """)
        r = cur.fetchone()

        # Top 5 comunas by predios
        top_comunas = conn.execute("""
            SELECT c.nombre, count(*) as total
            FROM catastro_actual a
            JOIN comunas_lookup c ON c.codigo = a.comuna
            GROUP BY c.nombre ORDER BY total DESC LIMIT 5
        """)

        # Distribution by destino
        destinos = conn.execute("""
            SELECT dc_cod_destino, count(*) as total,
                   round(count(*) * 100.0 / (SELECT count(*) FROM catastro_actual), 1) as pct,
                   round(avg(rc_avaluo_total)) as avg_avaluo
            FROM catastro_actual
            WHERE dc_cod_destino IS NOT NULL
            GROUP BY dc_cod_destino
            ORDER BY total DESC
        """)

        # Distribution by region
        regiones = conn.execute("""
            SELECT c.region, count(*) as total,
                   round(avg(a.rc_avaluo_total)) as avg_avaluo,
                   round(avg(COALESCE(NULLIF(a.dc_sup_terreno, 0), a.sup_construida_total))::numeric, 1) as avg_sup
            FROM catastro_actual a
            JOIN comunas_lookup c ON c.codigo = a.comuna
            GROUP BY c.region ORDER BY total DESC
        """)

        return {
            "total_predios": r[0],
            "total_comunas": r[1],
            "avg_avaluo": _n(r[2]),
            "total_avaluo_trillones": _n(r[3]),
            "mediana_avaluo": _n(r[4]),
            "avg_superficie": _n(r[5]),
            "total_contrib_billones": _n(r[6]),
            "top_comunas": [{"nombre": row[0], "total": row[1]} for row in top_comunas.fetchall()],
            "por_destino": [
                {"codigo": row[0], "nombre": DESTINO_LABELS.get(row[0], row[0]),
                 "total": row[1], "pct": _n(row[2]), "avg_avaluo": _n(row[3])}
                for row in destinos.fetchall()
            ],
            "por_region": [
                {"region": row[0], "total": row[1], "avg_avaluo": _n(row[2]), "avg_superficie": _n(row[3])}
                for row in regiones.fetchall()
            ],
        }


@router.get("/estadisticas/comunas")
def stats_comunas():
    with pool.connection() as conn:
        cur = conn.execute("""
            SELECT a.comuna, c.nombre, c.region,
                   count(*) as total_predios,
                   round(avg(a.rc_avaluo_total)) as avg_avaluo,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY a.rc_avaluo_total) as mediana_avaluo,
                   round(avg(COALESCE(NULLIF(a.dc_sup_terreno, 0), a.sup_construida_total))::numeric, 1) as avg_superficie,
                   round(avg(a.dc_contribucion_semestral)) as avg_contribucion,
                   count(CASE WHEN a.dc_cod_destino = 'H' THEN 1 END) as habitacional,
                   count(CASE WHEN a.dc_cod_destino = 'C' THEN 1 END) as comercial,
                   count(CASE WHEN a.dc_cod_destino NOT IN ('H','C') THEN 1 END) as otros
            FROM catastro_actual a
            LEFT JOIN comunas_lookup c ON c.codigo = a.comuna
            GROUP BY a.comuna, c.nombre, c.region
            ORDER BY c.region, c.nombre
        """)
        return [
            {
                "comuna": r[0], "nombre": r[1], "region": r[2],
                "total_predios": r[3],
                "avg_avaluo": _n(r[4]),
                "mediana_avaluo": _n(r[5]),
                "avg_superficie": _n(r[6]),
                "avg_contribucion": _n(r[7]),
                "habitacional": r[8],
                "comercial": r[9],
                "otros": r[10],
            }
            for r in cur.fetchall()
        ]


@router.get("/estadisticas/comunas/{codigo}")
def stats_comuna_detail(codigo: int):
    with pool.connection() as conn:
        cur = conn.execute("""
            SELECT count(*) as total,
                   round(avg(rc_avaluo_total)) as avg_avaluo,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY rc_avaluo_total) as mediana_avaluo,
                   round(avg(COALESCE(NULLIF(dc_sup_terreno, 0), sup_construida_total))::numeric, 1) as avg_sup,
                   round(avg(dc_contribucion_semestral)) as avg_contrib,
                   min(rc_avaluo_total) as min_avaluo,
                   max(rc_avaluo_total) as max_avaluo
            FROM catastro_actual
            WHERE comuna = %s
        """, [codigo])
        stats = cur.fetchone()

        destinos = conn.execute("""
            SELECT dc_cod_destino, count(*) as total,
                   round(avg(rc_avaluo_total)) as avg_avaluo,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY rc_avaluo_total) as mediana
            FROM catastro_actual
            WHERE comuna = %s AND dc_cod_destino IS NOT NULL
            GROUP BY dc_cod_destino
            ORDER BY total DESC
        """, [codigo])

        cl = conn.execute("SELECT nombre, region FROM comunas_lookup WHERE codigo = %s", [codigo])
        info = cl.fetchone()

        return {
            "codigo": codigo,
            "nombre": info[0] if info else None,
            "region": info[1] if info else None,
            "total_predios": stats[0],
            "avg_avaluo": _n(stats[1]),
            "mediana_avaluo": _n(stats[2]),
            "avg_superficie": _n(stats[3]),
            "avg_contribucion": _n(stats[4]),
            "min_avaluo": stats[5],
            "max_avaluo": stats[6],
            "por_destino": [
                {"destino": r[0], "nombre": DESTINO_LABELS.get(r[0], r[0]),
                 "total": r[1], "avg_avaluo": _n(r[2]), "mediana": _n(r[3])}
                for r in destinos.fetchall()
            ],
        }
