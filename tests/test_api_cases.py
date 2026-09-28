"""
tests/test_api_cases.py

Focused API tests for routes_cases and routes_analysis.

Covers the full create → analyze → graph flow using FastAPI TestClient.
All extraction runs with FORCE_FALLBACK=True (no Bob API key needed).
"""
from __future__ import annotations

import io
import os
from unittest.mock import patch

os.environ.setdefault("JAAL_TESTING", "1")

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _force_fallback_patch():
    """Context manager: patch FORCE_FALLBACK on the extractor's settings import."""
    return patch("backend.services.extractor.settings.FORCE_FALLBACK", True)


# ---------------------------------------------------------------------------
# 1. POST /api/cases — create
# ---------------------------------------------------------------------------

class TestCreateCase:
    def test_create_with_text_returns_case_id(self) -> None:
        resp = client.post("/api/cases", data={"text": "Suspect used 9876500001."})
        assert resp.status_code == 201
        body = resp.json()
        assert "case_id" in body
        assert body["status"] == "pending"

    def test_create_with_no_input_returns_422(self) -> None:
        resp = client.post("/api/cases")
        assert resp.status_code == 422

    def test_create_with_file_returns_case_id(self) -> None:
        csv_bytes = b"caller,receiver\n9876500001,8888800000"
        resp = client.post(
            "/api/cases",
            files=[("files", ("calls.csv", io.BytesIO(csv_bytes), "text/csv"))],
        )
        assert resp.status_code == 201
        assert "case_id" in resp.json()


# ---------------------------------------------------------------------------
# 2. POST /api/cases/{id}/analyze + GET /api/cases/{id}/graph
# ---------------------------------------------------------------------------

class TestAnalyzeAndGraph:
    def _create_case(self, text: str = "Call from 9876500001 to 8888800000.") -> str:
        resp = client.post("/api/cases", data={"text": text})
        assert resp.status_code == 201
        return resp.json()["case_id"]

    def test_analyze_returns_done_status(self) -> None:
        case_id = self._create_case()
        with _force_fallback_patch():
            resp = client.post(f"/api/cases/{case_id}/analyze")
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_analyze_returns_stats(self) -> None:
        case_id = self._create_case()
        with _force_fallback_patch():
            resp = client.post(f"/api/cases/{case_id}/analyze")
        stats = resp.json()["stats"]
        assert stats["chunks"] >= 1
        assert stats["nodes"] >= 0

    def test_graph_returns_graphpayload(self) -> None:
        case_id = self._create_case()
        with _force_fallback_patch():
            client.post(f"/api/cases/{case_id}/analyze")
        resp = client.get(f"/api/cases/{case_id}/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body

    def test_graph_before_analyze_returns_409(self) -> None:
        case_id = self._create_case()
        resp = client.get(f"/api/cases/{case_id}/graph")
        assert resp.status_code == 409

    def test_analyze_unknown_case_returns_404(self) -> None:
        resp = client.post("/api/cases/nonexistent-id/analyze")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. GET /api/demo/{scenario} — unknown scenario falls back to sample (not 404)
# ---------------------------------------------------------------------------

class TestDemoEndpoint:
    def test_missing_scenario_returns_sample_fallback(self) -> None:
        """Unknown scenarios fall back to sample_analysis.json (offline demo support)."""
        resp = client.get("/api/demo/scenario_that_does_not_exist")
        assert resp.status_code == 200
        assert "case_id" in resp.json()


# ---------------------------------------------------------------------------
# 4. GET /api/cases/{id}/analysis — returns real AnalysisResult after analyze
# ---------------------------------------------------------------------------

class TestAnalysisEndpoint:
    def test_analysis_returns_200_after_analyze(self) -> None:
        # Create + analyze first so the case is in 'done' state
        resp = client.post("/api/cases", data={"text": "9876500001 transferred 5000."})
        case_id = resp.json()["case_id"]
        with _force_fallback_patch():
            client.post(f"/api/cases/{case_id}/analyze")
        resp = client.get(f"/api/cases/{case_id}/analysis")
        assert resp.status_code == 200
        body = resp.json()
        assert "case_id" in body
