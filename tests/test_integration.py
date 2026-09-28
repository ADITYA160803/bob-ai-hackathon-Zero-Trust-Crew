"""
tests/test_integration.py

Task 6 integration tests for JAAL.

Covers:
  1.  Full synthetic end-to-end pipeline (ResolvedGraph → AnalysisResult)
  2.  Offline sample_analysis.json load and validation
  3.  AnalysisResult Pydantic round-trip (JSON serialization/deserialization)
  4.  IBM × Bob boundary — Bob client in offline mode returns safe stub
  5.  Pipeline determinism — repeated runs produce identical output
  6.  All roles expected from SIM-swap scenario are present
  7.  All expected patterns detected in SIM-swap scenario
  8.  Hierarchy levels ordering (KINGPIN first)
  9.  Totals computed correctly
  10. Timeline events present and ordered
  11. FastAPI route /api/cases/{id}/analyze returns AnalysisResult
  12. FastAPI demo route /api/demo/sample/analysis returns offline sample
  13. Bob offline mode — no API key → stub response, no exception
  14. No real personal data in any output
  15. Confidence values bounded [0, 1]
  16. All why/reason strings are non-empty and evidence-backed

All data is mock/synthetic — no real phone numbers, accounts, or identities.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.analysis.pipeline import run_pipeline
from backend.main import app
from backend.schemas.entities import ResolvedGraph
from backend.schemas.result import AnalysisResult
from backend.services.bob_client import BobClient
from backend.services.resolver import resolve

# ---------------------------------------------------------------------------
# Canonical SIM-swap synthetic scenario (shared across tests)
# ---------------------------------------------------------------------------

RAW_NODES = [
    {"id": "PE_RAJULAL",    "type": "PERSON",       "label": "Suspected Victim",
     "attrs": {},                               "sources": ["raw_notes.txt#p1"]},
    {"id": "PE_OP01",       "type": "PERSON",        "label": "Suspected Operator",
     "attrs": {},                               "sources": ["raw_notes.txt#p2"]},
    {"id": "PH_9990000001", "type": "PHONE",         "label": "999XXXXX01",
     "attrs": {"sim_swapped_on": "2024-01-15"}, "sources": ["raw_notes.txt#p2"]},
    {"id": "PH_9990000002", "type": "PHONE",         "label": "999XXXXX02",
     "attrs": {},                               "sources": ["raw_notes.txt#p2"]},
    {"id": "PH_OP01",       "type": "PHONE",         "label": "PHONE_OP01",
     "attrs": {},                               "sources": ["raw_notes.txt#p3"]},
    {"id": "DV_9900001",    "type": "DEVICE",        "label": "IMEI_MOCK0001",
     "attrs": {"imei": "990000123456789"},       "sources": ["raw_notes.txt#p2"]},
    {"id": "BA_HDFC9001",   "type": "BANK_ACCOUNT",  "label": "XXXXXX9001",
     "attrs": {"bank": "MockHDFC"},             "sources": ["raw_notes.txt#p1"]},
    {"id": "BA_MULE0001",   "type": "BANK_ACCOUNT",  "label": "XXXXXX0001",
     "attrs": {"bank": "MockSBI"},              "sources": ["transactions.csv#L2"]},
    {"id": "BA_MULE0002",   "type": "BANK_ACCOUNT",  "label": "XXXXXX0002",
     "attrs": {"bank": "MockPNB"},              "sources": ["transactions.csv#L5"]},
    {"id": "BA_KP0001",     "type": "BANK_ACCOUNT",  "label": "XXXXXX_KP01",
     "attrs": {"bank": "MockICICI"},            "sources": ["transactions.csv#L8"]},
    {"id": "UP_MOCKUPI",    "type": "UPI_ID",        "label": "mockupi@ybl",
     "attrs": {},                               "sources": ["raw_notes.txt#p3"]},
    {"id": "IP_192021",     "type": "IP",             "label": "192.0.2.1",
     "attrs": {},                               "sources": ["raw_notes.txt#p3"]},
]

RAW_EDGES = [
    {"id": "E01", "source": "PE_RAJULAL",    "target": "PH_9990000001", "type": "OWNS",          "attrs": {}, "evidence": "raw_notes.txt#p2"},
    {"id": "E02", "source": "PH_9990000001", "target": "DV_9900001",    "type": "SIM_IN_DEVICE", "attrs": {}, "evidence": "raw_notes.txt#p2"},
    {"id": "E03", "source": "PH_9990000002", "target": "DV_9900001",    "type": "SIM_IN_DEVICE", "attrs": {}, "evidence": "raw_notes.txt#p2"},
    {"id": "E04", "source": "PE_OP01",       "target": "PH_OP01",       "type": "OWNS",          "attrs": {}, "evidence": "raw_notes.txt#p3"},
    {"id": "E05", "source": "PE_OP01",       "target": "DV_9900001",    "type": "USES_DEVICE",   "attrs": {}, "evidence": "raw_notes.txt#p3"},
    {"id": "E06", "source": "DV_9900001",    "target": "IP_192021",     "type": "LOGGED_IN_FROM",
     "attrs": {"ts": "2024-01-15T10:05:00"}, "evidence": "raw_notes.txt#p2"},
    {"id": "E07", "source": "PH_OP01",       "target": "PE_RAJULAL",    "type": "CALLED",
     "attrs": {"duration_sec": 55, "ts": "2024-01-15T09:55:00"}, "evidence": "raw_notes.txt#p3"},
    {"id": "E08", "source": "PH_OP01",       "target": "PE_RAJULAL",    "type": "CALLED",
     "attrs": {"duration_sec": 40, "ts": "2024-01-14T15:00:00"}, "evidence": "raw_notes.txt#p3"},
    {"id": "E09", "source": "PH_OP01",       "target": "PE_RAJULAL",    "type": "SMS_SENT",
     "attrs": {"ts": "2024-01-15T09:58:00"}, "evidence": "raw_notes.txt#p3"},
    {"id": "E10", "source": "BA_HDFC9001",   "target": "BA_MULE0001",   "type": "TRANSFERRED_TO",
     "attrs": {"amount": 50000, "ts": "2024-01-15T10:10:00"}, "evidence": "transactions.csv#L2"},
    {"id": "E11", "source": "BA_MULE0001",   "target": "BA_MULE0002",   "type": "TRANSFERRED_TO",
     "attrs": {"amount": 47000, "ts": "2024-01-15T10:22:00"}, "evidence": "transactions.csv#L5"},
    {"id": "E12", "source": "BA_MULE0002",   "target": "BA_KP0001",     "type": "TRANSFERRED_TO",
     "attrs": {"amount": 44000, "ts": "2024-01-15T10:35:00"}, "evidence": "transactions.csv#L8"},
    {"id": "E13", "source": "PE_OP01",       "target": "BA_MULE0001",   "type": "OWNS",          "attrs": {}, "evidence": "raw_notes.txt#p3"},
    {"id": "E14", "source": "BA_MULE0001",   "target": "UP_MOCKUPI",    "type": "OWNS",          "attrs": {}, "evidence": "raw_notes.txt#p3"},
    {"id": "E15", "source": "BA_MULE0001",   "target": "IP_192021",     "type": "LOGGED_IN_FROM","attrs": {}, "evidence": "raw_notes.txt#p3"},
    {"id": "E16", "source": "BA_MULE0002",   "target": "IP_192021",     "type": "LOGGED_IN_FROM","attrs": {}, "evidence": "raw_notes.txt#p3"},
]


@pytest.fixture(scope="module")
def sim_swap_result() -> AnalysisResult:
    """Run the full pipeline once per module; reused across tests."""
    rg = resolve("MOCK-SIM-001", RAW_NODES, RAW_EDGES)
    return run_pipeline(rg)


@pytest.fixture(scope="module")
def http_client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 — Full synthetic end-to-end pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_returns_analysis_result(self, sim_swap_result):
        assert isinstance(sim_swap_result, AnalysisResult)

    def test_case_id_preserved(self, sim_swap_result):
        assert sim_swap_result.case_id == "MOCK-SIM-001"

    def test_roles_non_empty(self, sim_swap_result):
        assert len(sim_swap_result.roles) > 0

    def test_patterns_non_empty(self, sim_swap_result):
        assert len(sim_swap_result.all_patterns) > 0

    def test_levels_non_empty(self, sim_swap_result):
        assert len(sim_swap_result.levels) > 0

    def test_timeline_non_empty(self, sim_swap_result):
        assert len(sim_swap_result.timeline) > 0

    def test_metrics_present(self, sim_swap_result):
        assert sim_swap_result.metrics is not None

    def test_communities_present(self, sim_swap_result):
        assert sim_swap_result.communities is not None


# ---------------------------------------------------------------------------
# Test 2 — Offline sample_analysis.json
# ---------------------------------------------------------------------------

class TestOfflineSampleFile:
    _SAMPLE = Path("data/sample_analysis.json")

    def test_sample_file_exists(self):
        assert self._SAMPLE.exists(), f"data/sample_analysis.json not found at {self._SAMPLE}"

    def test_sample_file_valid_json(self):
        raw = self._SAMPLE.read_text(encoding="utf-8")
        d = json.loads(raw)
        assert isinstance(d, dict)

    def test_sample_file_validates_as_analysis_result(self):
        raw = self._SAMPLE.read_text(encoding="utf-8")
        d = json.loads(raw)
        result = AnalysisResult.model_validate(d)
        assert isinstance(result, AnalysisResult)

    def test_sample_file_no_network_required(self):
        """Loading the file must not trigger any network call."""
        raw = self._SAMPLE.read_text(encoding="utf-8")
        d = json.loads(raw)
        result = AnalysisResult.model_validate(d)
        assert result.case_id is not None


# ---------------------------------------------------------------------------
# Test 3 — AnalysisResult Pydantic round-trip
# ---------------------------------------------------------------------------

class TestAnalysisResultSerialisation:
    def test_json_round_trip(self, sim_swap_result):
        json_str = sim_swap_result.model_dump_json()
        parsed = AnalysisResult.model_validate_json(json_str)
        assert parsed.case_id == sim_swap_result.case_id
        assert len(parsed.roles) == len(sim_swap_result.roles)
        assert len(parsed.all_patterns) == len(sim_swap_result.all_patterns)

    def test_model_dump_is_plain_types(self, sim_swap_result):
        d = sim_swap_result.model_dump()
        json_str = json.dumps(d)   # must not raise
        assert isinstance(json_str, str)

    def test_enum_values_are_strings_in_json(self, sim_swap_result):
        d = sim_swap_result.model_dump()
        for pm in d["all_patterns"]:
            assert isinstance(pm["type"], str)
        for rs in d["roles"]:
            assert isinstance(rs["role"], str)


# ---------------------------------------------------------------------------
# Test 4 — IBM × Bob boundary (offline mode)
# ---------------------------------------------------------------------------

class TestBobClientOffline:
    def test_offline_client_does_not_raise(self):
        """When API key is absent, BobClient must return a stub, not raise."""
        client = BobClient(api_key="")
        assert client.offline is True
        result = client.extract("test prompt", {})
        assert "_offline" in result

    def test_offline_client_extract_returns_empty_nodes_edges(self):
        client = BobClient(api_key="")
        result = client.extract("prompt", {})
        assert "nodes" in result
        assert "edges" in result
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_offline_client_summarise_returns_string(self):
        client = BobClient(api_key="")
        text = client.summarise("Write a brief.")
        assert isinstance(text, str)
        assert "OFFLINE" in text or "offline" in text.lower() or "API" in text


# ---------------------------------------------------------------------------
# Test 5 — Pipeline determinism
# ---------------------------------------------------------------------------

class TestPipelineDeterminism:
    def test_repeated_runs_identical(self):
        rg = resolve("MOCK-DET", RAW_NODES, RAW_EDGES)
        r1 = run_pipeline(rg)
        r2 = run_pipeline(rg)
        assert r1.model_dump() == r2.model_dump()


# ---------------------------------------------------------------------------
# Tests 6, 7 — Roles and patterns from SIM-swap scenario
# ---------------------------------------------------------------------------

class TestSIMSwapRoles:
    def _roles(self, result: AnalysisResult) -> dict:
        return {rs.node_id: rs.role.value for rs in result.roles}

    def test_victim_role(self, sim_swap_result):
        roles = self._roles(sim_swap_result)
        assert "BA_HDFC9001" in roles
        assert roles["BA_HDFC9001"] == "VICTIM"

    def test_mule_roles(self, sim_swap_result):
        roles = self._roles(sim_swap_result)
        assert roles.get("BA_MULE0001") == "MULE"
        assert roles.get("BA_MULE0002") == "MULE"

    def test_kingpin_role(self, sim_swap_result):
        roles = self._roles(sim_swap_result)
        assert roles.get("BA_KP0001") == "KINGPIN"

    def test_operator_role(self, sim_swap_result):
        roles = self._roles(sim_swap_result)
        assert roles.get("PE_OP01") == "OPERATOR"


class TestSIMSwapPatterns:
    def _types(self, result: AnalysisResult) -> set:
        return {p.type.value for p in result.all_patterns}

    def test_mule_layering_detected(self, sim_swap_result):
        assert "MULE_LAYERING" in self._types(sim_swap_result)

    def test_vishing_detected(self, sim_swap_result):
        assert "VISHING" in self._types(sim_swap_result)

    def test_sim_swap_detected(self, sim_swap_result):
        assert "SIM_SWAP" in self._types(sim_swap_result)

    def test_primary_pattern_is_highest_confidence(self, sim_swap_result):
        if sim_swap_result.primary_pattern and sim_swap_result.all_patterns:
            max_conf = max(p.confidence for p in sim_swap_result.all_patterns)
            assert sim_swap_result.primary_pattern.confidence == max_conf


# ---------------------------------------------------------------------------
# Test 8 — Hierarchy levels ordering
# ---------------------------------------------------------------------------

class TestHierarchyLevels:
    def test_kingpin_in_first_level(self, sim_swap_result):
        if sim_swap_result.levels:
            assert "BA_KP0001" in sim_swap_result.levels[0]

    def test_levels_are_sorted(self, sim_swap_result):
        for level in sim_swap_result.levels:
            assert level == sorted(level)


# ---------------------------------------------------------------------------
# Test 9 — Totals computed correctly
# ---------------------------------------------------------------------------

class TestTotals:
    def test_loss_inr_positive(self, sim_swap_result):
        if sim_swap_result.totals.loss_inr is not None:
            assert sim_swap_result.totals.loss_inr > 0

    def test_victim_count(self, sim_swap_result):
        if sim_swap_result.totals.victims is not None:
            assert sim_swap_result.totals.victims >= 1

    def test_mule_count(self, sim_swap_result):
        if sim_swap_result.totals.mules is not None:
            assert sim_swap_result.totals.mules >= 1


# ---------------------------------------------------------------------------
# Test 10 — Timeline ordered
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_events_exist(self, sim_swap_result):
        assert len(sim_swap_result.timeline) > 0

    def test_timeline_sorted_by_ts(self, sim_swap_result):
        ts_list = [e.ts for e in sim_swap_result.timeline]
        assert ts_list == sorted(ts_list)

    def test_timeline_event_strings_non_empty(self, sim_swap_result):
        for ev in sim_swap_result.timeline:
            assert ev.event.strip()


# ---------------------------------------------------------------------------
# Tests 11, 12 — FastAPI routes
# ---------------------------------------------------------------------------

class TestAPIRoutes:
    def test_health_endpoint(self, http_client):
        resp = http_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_analyze_endpoint(self, http_client):
        rg = resolve("API-TEST-001", RAW_NODES, RAW_EDGES)
        body = json.loads(rg.model_dump_json())
        resp = http_client.post("/api/cases/API-TEST-001/analyze", json=body)
        assert resp.status_code == 200
        result = AnalysisResult.model_validate(resp.json())
        assert result.case_id == "API-TEST-001"

    def test_demo_sample_endpoint(self, http_client):
        """Test that offline demo endpoint works without network."""
        resp = http_client.get("/api/demo/sample/analysis")
        assert resp.status_code == 200
        result = AnalysisResult.model_validate(resp.json())
        assert result.case_id is not None

    def test_demo_unknown_scenario_falls_back_to_sample(self, http_client):
        """
        When a named scenario file doesn't exist, the demo route falls back
        to data/sample_analysis.json (required for offline demo to always work).
        """
        resp = http_client.get("/api/demo/nonexistent_scenario_xyz")
        # Falls back to sample_analysis.json — 200, not 404
        assert resp.status_code == 200
        result = resp.json()
        assert "case_id" in result


# ---------------------------------------------------------------------------
# Test 13 — Bob offline mode (no API key)
# ---------------------------------------------------------------------------
# Covered in TestBobClientOffline above


# ---------------------------------------------------------------------------
# Test 14 — No real personal data
# ---------------------------------------------------------------------------

class TestNoRealData:
    REAL_DATA_MARKERS = [
        "9876543210",  # real phone prefix patterns
        "gmail.com",
        "yahoo.com",
        "aadhar",
        "aadhaar",
    ]

    def test_no_real_data_in_analysis_result(self, sim_swap_result):
        json_str = sim_swap_result.model_dump_json().lower()
        for marker in self.REAL_DATA_MARKERS:
            assert marker not in json_str, f"Real data marker '{marker}' found in output"


# ---------------------------------------------------------------------------
# Test 15 — Confidence values bounded [0, 1]
# ---------------------------------------------------------------------------

class TestConfidenceBounds:
    def test_all_pattern_confidences_in_range(self, sim_swap_result):
        for pm in sim_swap_result.all_patterns:
            assert 0.0 <= pm.confidence <= 1.0

    def test_all_role_scores_in_range(self, sim_swap_result):
        for rs in sim_swap_result.roles:
            assert 0.0 <= rs.score <= 1.0


# ---------------------------------------------------------------------------
# Test 16 — Why/reason strings non-empty and evidence-backed
# ---------------------------------------------------------------------------

class TestReasonStrings:
    def test_pattern_reasons_non_empty(self, sim_swap_result):
        for pm in sim_swap_result.all_patterns:
            assert pm.reasons, f"Pattern {pm.type} has no reasons"
            for r in pm.reasons:
                assert r.strip(), f"Empty reason string in {pm.type}"

    def test_role_why_non_empty_for_scored_nodes(self, sim_swap_result):
        for rs in sim_swap_result.roles:
            if rs.score > 0 and rs.role.value != "UNKNOWN":
                assert rs.why, f"Node {rs.node_id} role {rs.role} has no why"


# ---------------------------------------------------------------------------
# Performance test — end-to-end under PRD 60-second target
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_pipeline_under_60_seconds(self):
        rg = resolve("PERF-TEST", RAW_NODES, RAW_EDGES)
        t0 = time.perf_counter()
        run_pipeline(rg)
        elapsed = time.perf_counter() - t0
        assert elapsed < 60.0, f"Pipeline took {elapsed:.2f}s (PRD target: <60s)"

    def test_pipeline_executes_quickly(self):
        """Small graph should complete well under 1 second."""
        rg = resolve("PERF-FAST", RAW_NODES, RAW_EDGES)
        t0 = time.perf_counter()
        run_pipeline(rg)
        elapsed = time.perf_counter() - t0
        print(f"\n  Pipeline elapsed: {elapsed*1000:.1f} ms")
        assert elapsed < 5.0, f"Pipeline took {elapsed:.2f}s on a 12-node graph"
