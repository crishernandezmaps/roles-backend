from fastapi import FastAPI
from logging_config import setup_logging

setup_logging()
from fastapi.middleware.cors import CORSMiddleware
from config import FRONTEND_URL
from routers import predios, estadisticas, health, descargas, geocode

app = FastAPI(
    title="Roles Tremen - Explorador Catastral SII",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["Content-Type", "Accept"],
)

app.include_router(health.router, prefix="/api")
app.include_router(predios.router, prefix="/api")
app.include_router(estadisticas.router, prefix="/api")
app.include_router(descargas.router, prefix="/api")
app.include_router(geocode.router, prefix="/api")
