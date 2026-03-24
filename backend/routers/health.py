from fastapi import APIRouter
from db import pool

router = APIRouter()

@router.get("/health")
def health():
    with pool.connection() as conn:
        row = conn.execute("SELECT count(*) FROM catastro_actual")
        count = row.fetchone()[0]
    return {"status": "ok", "rows": count}
