"""
JAAL — FastAPI application entry point.

Starts the app, configures CORS for the Vite dev server, exposes
GET /api/health, and registers API routers from backend/api/ as they
are added in later phases.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings

app = FastAPI(
    title="JAAL",
    description="Fraud network intelligence — AI-assisted analysis. "
                "Requires verification by the investigating officer.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite dev server (and any origins listed in config)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from backend.api.routes_cases import router as cases_router
from backend.api.routes_analysis import router as analysis_router
from backend.api.routes_report import router as report_router

app.include_router(cases_router)
app.include_router(analysis_router)
app.include_router(report_router)


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health", tags=["meta"])
def health_check() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/health", tags=["meta"])
def health_check_root() -> dict[str, str]:
    """Liveness probe (root alias for test_integration.py)."""
    return {"status": "ok"}
