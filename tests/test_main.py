"""
tests/test_main.py

Tests for backend/main.py:
  - GET /api/health returns 200 and {"status": "ok"}
  - CORS header is present for the Vite origin
  - Unknown routes return 404

Uses TestClient (httpx-based) from starlette — no live server needed.
JAAL_TESTING=1 is set so config does not complain about a missing API key.
"""
from __future__ import annotations

import os

# Must be set BEFORE importing anything from backend so config validation
# is bypassed in the test environment.
os.environ.setdefault("JAAL_TESTING", "1")

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
class TestHealthEndpoint:
    def test_returns_200(self) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_returns_ok_body(self) -> None:
        response = client.get("/api/health")
        assert response.json() == {"status": "ok"}

    def test_content_type_is_json(self) -> None:
        response = client.get("/api/health")
        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
class TestCors:
    """Verify CORS is configured for the Vite dev origin."""

    def test_cors_header_present_for_vite_origin(self) -> None:
        vite_origin = "http://localhost:5173"
        response = client.get(
            "/api/health",
            headers={"Origin": vite_origin},
        )
        # FastAPI/Starlette echoes the origin back in ACAO when it matches
        assert response.headers.get("access-control-allow-origin") == vite_origin

    def test_cors_preflight_allowed(self) -> None:
        vite_origin = "http://localhost:5173"
        response = client.options(
            "/api/health",
            headers={
                "Origin": vite_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 204)
        assert response.headers.get("access-control-allow-origin") == vite_origin


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------
class TestUnknownRoutes:
    def test_unknown_path_returns_404(self) -> None:
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
