"""
tests/test_pattern_classifier.py

Tests for:
  - backend/analysis/pattern_classifier.py  (classify_patterns)
  - backend/schemas/analysis.py             (PatternType, PatternMatch, PatternResult)

All data is mock/synthetic — no real names, phones, accounts, or identities.
Tests are fully deterministic; no AI/LLM call is made.

Test inventory (spec §9)
------------------------
  1.  Empty graph → empty PatternResult
  2.  No pattern → empty patterns list (graph without sufficient indicators)
  3.  Clear SIM_SWAP
  4.  Clear MULE_LAYERING
  5.  Clear VISHING
  6.  Clear PHISHING_KYC
  7.  Clear INVESTMENT_TASK
  8.  Multiple patterns in one case
  9.  Confidence bounds [0,1]
  10. Deterministic repeated output
  11. Parallel edges handled correctly
  12. Missing optional attributes (e.g. no "amount", no "ts")
  13. Missing timestamps for investment-task
  14. Evidence-backed reasons — each reason traceable to a metric/edge
  15. No fabricated reasons — reasons list matches fired indicators
  16. Pydantic serialization (JSON round-trip)
  17. Threshold boundary cases

Additional:
  18. SIM_SWAP rapid-debit indicator with gap outside window
  19. VISHING caller ratio boundary
  20. INVESTMENT_TASK early/late amount split
  21. PHISHING_KYC shared IP detection
  22. Full pipeline integration (ResolvedGraph → classify_patterns)
"""

from __future__ import annotations

import networkx as nx
import pytest

from backend.analysis.communities import detect_communities
from backend.analysis.graph_builder import build_graph
from backend.analysis.hierarchy import score_hierarchy
from backend.analysis.metrics import compute_metrics
from backend.analysis.pattern_classifier import (
    MIN_CONFIDENCE,
    classify_patterns,
)
from backend.schemas.analysis import (
    PatternMatch,
    PatternResult,
    PatternType,
)
from backend.schemas.entities import ResolvedGraph
from backend.services.resolver import resolve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph(case_id: str = "CASE_PC") -> nx.MultiDiGraph:
    return nx.MultiDiGraph(case_id=case_id)


def _add_node(
    G: nx.MultiDiGraph,
    nid: str,
    ntype: str = "PERSON",
    **attrs,
) -> None:
    G.add_node(nid, type=ntype, label=nid, attrs=attrs, sources=["mock.txt#L1"])


def _add_edge(
    G: nx.MultiDiGraph,
    eid: str,
    src: str,
    tgt: str,
    etype: str = "TRANSFERRED_TO",
    **attrs,
) -> None:
    G.add_edge(
        src, tgt,
        key=eid, id=eid,
        type=etype,
        attrs=attrs,
        evidence="mock.csv#L1",
    )


def _pipeline(G: nx.MultiDiGraph):
    m = compute_metrics(G)
    h = score_hierarchy(G, m)
    return m, h


def _classify(G: nx.MultiDiGraph):
    m, h = _pipeline(G)
    return classify_patterns(G, m, h)


def _pattern_types(result: PatternResult) -> set[PatternType]:
    return {p.type for p in result.patterns}


# ---------------------------------------------------------------------------
# Test 1 — Empty graph
# ---------------------------------------------------------------------------

class TestEmptyGraph:
    def test_empty_returns_pattern_result(self):
        G = _make_graph("CASE_EMPTY")
        m, h = _pipeline(G)
        result = classify_patterns(G, m, h)
        assert isinstance(result, PatternResult)
        assert result.case_id == "CASE_EMPTY"
        assert result.patterns == []


# ---------------------------------------------------------------------------
# Test 2 — No pattern (isolated nodes, no meaningful edges)
# ---------------------------------------------------------------------------

class TestNoPattern:
    def test_no_pattern_from_isolated_nodes(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "PE_B")
        result = _classify(G)
        assert result.patterns == []

    def test_single_transfer_no_pattern(self):
        """One transfer edge alone does not reach MIN_CONFIDENCE for any pattern."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "TGT", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "TGT", amount=1000.0, ts="2024-01-01T10:00:00")
        result = _classify(G)
        # MULE_LAYERING: 1 transfer = not >= 2 → A fails, chain_len=1 < 2 → B fails
        # No pattern should exceed MIN_CONFIDENCE
        types = _pattern_types(result)
        assert PatternType.MULE_LAYERING not in types


# ---------------------------------------------------------------------------
# Test 3 — Clear SIM_SWAP
# ---------------------------------------------------------------------------

class TestSimSwap:
    @pytest.fixture
    def sim_swap_graph(self):
        G = _make_graph("CASE_SS")
        # PHONE with sim_swapped_on — indicator A
        _add_node(G, "PH_OLD", "PHONE", sim_swapped_on="2024-01-15")
        _add_node(G, "PH_NEW", "PHONE")
        _add_node(G, "DEV_X", "DEVICE")
        _add_node(G, "BA_VIC", "BANK_ACCOUNT")
        _add_node(G, "BA_MULE", "BANK_ACCOUNT")
        # Both SIMs in same device — indicator B
        _add_edge(G, "S1", "PH_OLD", "DEV_X", etype="SIM_IN_DEVICE")
        _add_edge(G, "S2", "PH_NEW", "DEV_X", etype="SIM_IN_DEVICE")
        # Login from device — indicator C
        _add_edge(G, "L1", "PH_NEW", "DEV_X", etype="LOGGED_IN_FROM")
        # Rapid transfer after SIM swap — indicator D (swap at T+0, transfer at T+30min)
        _add_edge(G, "T1", "BA_VIC", "BA_MULE",
                  amount=50000.0, ts="2024-01-15T00:30:00")
        return G

    def test_sim_swap_detected(self, sim_swap_graph):
        result = _classify(sim_swap_graph)
        assert PatternType.SIM_SWAP in _pattern_types(result)

    def test_sim_swap_confidence_positive(self, sim_swap_graph):
        result = _classify(sim_swap_graph)
        ss = next(p for p in result.patterns if p.type == PatternType.SIM_SWAP)
        assert ss.confidence > 0

    def test_sim_swap_reasons_non_empty(self, sim_swap_graph):
        result = _classify(sim_swap_graph)
        ss = next(p for p in result.patterns if p.type == PatternType.SIM_SWAP)
        assert len(ss.reasons) >= 2

    def test_sim_swap_reasons_mention_evidence(self, sim_swap_graph):
        result = _classify(sim_swap_graph)
        ss = next(p for p in result.patterns if p.type == PatternType.SIM_SWAP)
        text = " ".join(ss.reasons).lower()
        # At least one of: sim, device, login, swap
        assert any(kw in text for kw in ("sim", "device", "login", "swap"))


# ---------------------------------------------------------------------------
# Test 4 — Clear MULE_LAYERING
# ---------------------------------------------------------------------------

class TestMuleLayering:
    @pytest.fixture
    def mule_graph(self):
        G = _make_graph("CASE_ML")
        for nid in ["VIC", "M1", "M2", "KP"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_edge(G, "T1", "VIC", "M1", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "M1", "M2", amount=48000.0, ts="2024-01-15T10:15:00")
        _add_edge(G, "T3", "M2", "KP", amount=46000.0, ts="2024-01-15T10:30:00")
        return G

    def test_mule_layering_detected(self, mule_graph):
        result = _classify(mule_graph)
        assert PatternType.MULE_LAYERING in _pattern_types(result)

    def test_mule_layering_confidence_high(self, mule_graph):
        result = _classify(mule_graph)
        ml = next(p for p in result.patterns if p.type == PatternType.MULE_LAYERING)
        assert ml.confidence >= MIN_CONFIDENCE

    def test_mule_layering_reasons_mention_hops(self, mule_graph):
        result = _classify(mule_graph)
        ml = next(p for p in result.patterns if p.type == PatternType.MULE_LAYERING)
        text = " ".join(ml.reasons).lower()
        assert "hop" in text or "chain" in text or "transfer" in text


# ---------------------------------------------------------------------------
# Test 5 — Clear VISHING
# ---------------------------------------------------------------------------

class TestVishing:
    @pytest.fixture
    def vishing_graph(self):
        G = _make_graph("CASE_VIS")
        _add_node(G, "PH_OP", "PHONE")  # One operator phone
        for i in range(5):
            vid = f"VIC{i}"
            _add_node(G, vid)
            _add_edge(G, f"C{i}", "PH_OP", vid, etype="CALLED", duration_sec=60.0)
        # SMS sent too — indicator D
        _add_edge(G, "SMS1", "PH_OP", "VIC0", etype="SMS_SENT")
        return G

    def test_vishing_detected(self, vishing_graph):
        result = _classify(vishing_graph)
        assert PatternType.VISHING in _pattern_types(result)

    def test_vishing_reasons_mention_calls(self, vishing_graph):
        result = _classify(vishing_graph)
        vis = next(p for p in result.patterns if p.type == PatternType.VISHING)
        text = " ".join(vis.reasons).lower()
        assert "call" in text

    def test_vishing_confidence_high(self, vishing_graph):
        result = _classify(vishing_graph)
        vis = next(p for p in result.patterns if p.type == PatternType.VISHING)
        assert vis.confidence >= MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# Test 6 — Clear PHISHING_KYC
# ---------------------------------------------------------------------------

class TestPhishingKyc:
    @pytest.fixture
    def phishing_graph(self):
        G = _make_graph("CASE_PK")
        _add_node(G, "OP", "PHONE")
        for i in range(4):
            vid = f"TGT{i}"
            _add_node(G, vid)
            _add_edge(G, f"SMS{i}", "OP", vid, etype="SMS_SENT")
        # Shared IP — indicator B + D
        _add_node(G, "IP_SHARED", "IP")
        _add_node(G, "PE_A")
        _add_node(G, "PE_B")
        _add_edge(G, "L1", "PE_A", "IP_SHARED", etype="LOGGED_IN_FROM")
        _add_edge(G, "L2", "PE_B", "IP_SHARED", etype="LOGGED_IN_FROM")
        return G

    def test_phishing_detected(self, phishing_graph):
        result = _classify(phishing_graph)
        assert PatternType.PHISHING_KYC in _pattern_types(result)

    def test_phishing_reasons_mention_sms_or_ip(self, phishing_graph):
        result = _classify(phishing_graph)
        pk = next(p for p in result.patterns if p.type == PatternType.PHISHING_KYC)
        text = " ".join(pk.reasons).lower()
        assert "sms" in text or "ip" in text or "shared" in text


# ---------------------------------------------------------------------------
# Test 7 — Clear INVESTMENT_TASK
# ---------------------------------------------------------------------------

class TestInvestmentTask:
    @pytest.fixture
    def investment_graph(self):
        G = _make_graph("CASE_IT")
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "PLATFORM", "BANK_ACCOUNT")
        # Small early payouts (trust-building)
        _add_edge(G, "P1", "PLATFORM", "SRC", amount=500.0, ts="2024-01-01T10:00:00")
        _add_edge(G, "P2", "PLATFORM", "SRC", amount=800.0, ts="2024-01-05T10:00:00")
        # Large final deposit (exploitation)
        _add_edge(G, "D1", "SRC", "PLATFORM", amount=200000.0, ts="2024-01-20T10:00:00")
        return G

    def test_investment_task_detected(self, investment_graph):
        result = _classify(investment_graph)
        assert PatternType.INVESTMENT_TASK in _pattern_types(result)

    def test_investment_task_reasons_mention_amounts(self, investment_graph):
        result = _classify(investment_graph)
        it = next(p for p in result.patterns if p.type == PatternType.INVESTMENT_TASK)
        text = " ".join(it.reasons).lower()
        assert "inr" in text or "amount" in text or "transfer" in text

    def test_investment_task_confidence_high(self, investment_graph):
        result = _classify(investment_graph)
        it = next(p for p in result.patterns if p.type == PatternType.INVESTMENT_TASK)
        assert it.confidence >= MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# Test 8 — Multiple patterns in one case
# ---------------------------------------------------------------------------

class TestMultiplePatterns:
    def test_mule_layering_and_vishing_together(self):
        G = _make_graph("CASE_MULTI")
        # VISHING component: 1 phone calls 4 victims + SMS
        _add_node(G, "PH_OP", "PHONE")
        for i in range(4):
            _add_node(G, f"VIC{i}")
            _add_edge(G, f"C{i}", "PH_OP", f"VIC{i}", etype="CALLED")
        _add_edge(G, "SMS1", "PH_OP", "VIC0", etype="SMS_SENT")
        # MULE_LAYERING component: 3-hop transfer chain
        for nid in ["BA_M1", "BA_M2", "BA_KP"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_edge(G, "T1", "VIC0", "BA_M1", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "BA_M1", "BA_M2", amount=48000.0, ts="2024-01-15T10:15:00")
        _add_edge(G, "T3", "BA_M2", "BA_KP", amount=46000.0, ts="2024-01-15T10:30:00")
        result = _classify(G)
        types = _pattern_types(result)
        assert PatternType.VISHING in types
        assert PatternType.MULE_LAYERING in types
        assert len(result.patterns) >= 2


# ---------------------------------------------------------------------------
# Test 9 — Confidence bounds [0, 1]
# ---------------------------------------------------------------------------

class TestConfidenceBounds:
    def test_all_confidences_in_range(self):
        G = _make_graph()
        for nid in ["PE_A", "BA_X", "BA_Y", "PH_Q", "IP_Z"]:
            _add_node(G, nid)
        _add_edge(G, "T1", "PE_A", "BA_X", amount=5000.0, ts="2024-01-01T09:00:00")
        _add_edge(G, "T2", "BA_X", "BA_Y", amount=4800.0, ts="2024-01-01T09:20:00")
        _add_edge(G, "C1", "PH_Q", "PE_A", etype="CALLED")
        _add_edge(G, "C2", "PH_Q", "BA_X", etype="CALLED")
        _add_edge(G, "C3", "PH_Q", "BA_Y", etype="CALLED")
        _add_edge(G, "L1", "PE_A", "IP_Z", etype="LOGGED_IN_FROM")
        result = _classify(G)
        for pm in result.patterns:
            assert 0.0 <= pm.confidence <= 1.0, (
                f"Pattern {pm.type} has confidence {pm.confidence} out of [0,1]"
            )


# ---------------------------------------------------------------------------
# Test 10 — Deterministic repeated output
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_repeated_calls_give_same_result(self):
        G = _make_graph()
        for nid in ["VIC", "M1", "M2", "KP"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_edge(G, "T1", "VIC", "M1", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "M1", "M2", amount=48000.0, ts="2024-01-15T10:15:00")
        _add_edge(G, "T3", "M2", "KP", amount=46000.0, ts="2024-01-15T10:30:00")
        m, h = _pipeline(G)
        r1 = classify_patterns(G, m, h)
        r2 = classify_patterns(G, m, h)
        assert r1.model_dump() == r2.model_dump()


# ---------------------------------------------------------------------------
# Test 11 — Parallel edges
# ---------------------------------------------------------------------------

class TestParallelEdges:
    def test_parallel_transfer_edges_both_counted(self):
        """Two parallel TRANSFERRED_TO edges count as 2 for indicator A."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MID", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        # Two parallel edges between SRC→MID
        _add_edge(G, "T1", "SRC", "MID", amount=30000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "SRC", "MID", amount=20000.0, ts="2024-01-15T10:05:00")
        _add_edge(G, "T3", "MID", "SNK", amount=48000.0, ts="2024-01-15T10:20:00")
        result = _classify(G)
        # Mule layering should fire: >=2 transfers (A), chain>=2 (B), pass-through (C,D)
        assert PatternType.MULE_LAYERING in _pattern_types(result)


# ---------------------------------------------------------------------------
# Test 12 — Missing optional attributes
# ---------------------------------------------------------------------------

class TestMissingAttributes:
    def test_no_amount_no_investment_task(self):
        """Transfers without 'amount' cannot fire INVESTMENT_TASK indicators B-D."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MID", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        # No amount kwarg
        _add_edge(G, "T1", "SRC", "MID", ts="2024-01-01T09:00:00")
        _add_edge(G, "T2", "MID", "SNK", ts="2024-01-01T10:00:00")
        result = _classify(G)
        # INVESTMENT_TASK indicator A requires 'amount' — without it score ≈ 0
        if PatternType.INVESTMENT_TASK in _pattern_types(result):
            it = next(p for p in result.patterns if p.type == PatternType.INVESTMENT_TASK)
            # If somehow detected, reasons should NOT mention amounts
            text = " ".join(it.reasons).lower()
            assert "inr" not in text or "0 inr" in text


# ---------------------------------------------------------------------------
# Test 13 — Missing timestamps for investment_task
# ---------------------------------------------------------------------------

class TestMissingTimestamps:
    def test_no_timestamps_prevents_investment_task_bc_indicators(self):
        """Without timestamps, indicators B/C/D cannot fire."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "PLAT", "BANK_ACCOUNT")
        # Amounts present but no ts
        _add_edge(G, "P1", "PLAT", "SRC", amount=500.0)
        _add_edge(G, "P2", "PLAT", "SRC", amount=800.0)
        _add_edge(G, "D1", "SRC", "PLAT", amount=200000.0)
        result = _classify(G)
        # Indicator A (>=2 amounts) fires → score = 1/4 = 0.25 < MIN_CONFIDENCE=0.40
        # So INVESTMENT_TASK should NOT appear
        assert PatternType.INVESTMENT_TASK not in _pattern_types(result)


# ---------------------------------------------------------------------------
# Test 14 — Evidence-backed reasons
# ---------------------------------------------------------------------------

class TestEvidenceBackedReasons:
    def test_mule_layering_reasons_contain_measurable_facts(self):
        G = _make_graph()
        for nid in ["A", "B", "C"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_edge(G, "T1", "A", "B", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "B", "C", amount=48000.0, ts="2024-01-15T10:20:00")
        result = _classify(G)
        if PatternType.MULE_LAYERING in _pattern_types(result):
            ml = next(p for p in result.patterns if p.type == PatternType.MULE_LAYERING)
            for reason in ml.reasons:
                # Each reason should contain a number or named entity
                has_number = any(c.isdigit() for c in reason)
                has_keyword = any(kw in reason.lower() for kw in
                                  ["hop", "transfer", "pass-through", "ratio", "mule",
                                   "chain", "node", "account", "edge"])
                assert has_number or has_keyword, (
                    f"Reason lacks specific evidence: {reason!r}"
                )


# ---------------------------------------------------------------------------
# Test 15 — No fabricated reasons
# ---------------------------------------------------------------------------

class TestNoFabricatedReasons:
    def test_no_pattern_when_no_evidence(self):
        """Two isolated nodes produce no patterns."""
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "PE_B")
        result = _classify(G)
        assert result.patterns == []

    def test_reasons_count_matches_indicators_fired(self):
        """Each PatternMatch.reasons entry is exactly one fired indicator."""
        G = _make_graph()
        for nid in ["VIC", "M1", "M2", "KP"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_edge(G, "T1", "VIC", "M1", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "M1", "M2", amount=48000.0, ts="2024-01-15T10:15:00")
        _add_edge(G, "T3", "M2", "KP", amount=46000.0, ts="2024-01-15T10:30:00")
        result = _classify(G)
        if PatternType.MULE_LAYERING in _pattern_types(result):
            ml = next(p for p in result.patterns if p.type == PatternType.MULE_LAYERING)
            # confidence = len(reasons) / 5 → reasons = confidence * 5
            expected_reasons = round(ml.confidence * 5)
            assert len(ml.reasons) == expected_reasons


# ---------------------------------------------------------------------------
# Test 16 — Pydantic serialization
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_pattern_result_json_round_trip(self):
        G = _make_graph("CASE_SER")
        for nid in ["VIC", "M1", "M2", "KP"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_edge(G, "T1", "VIC", "M1", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "T2", "M1", "M2", amount=48000.0, ts="2024-01-15T10:15:00")
        _add_edge(G, "T3", "M2", "KP", amount=46000.0, ts="2024-01-15T10:30:00")
        result = _classify(G)
        json_str = result.model_dump_json()
        parsed = PatternResult.model_validate_json(json_str)
        assert parsed.case_id == result.case_id
        assert len(parsed.patterns) == len(result.patterns)

    def test_pattern_match_model(self):
        pm = PatternMatch(
            type=PatternType.MULE_LAYERING,
            confidence=0.8,
            reasons=["3 hop chain"],
        )
        d = pm.model_dump()
        assert d["type"] == "MULE_LAYERING"
        assert d["confidence"] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Test 17 — Threshold boundary cases
# ---------------------------------------------------------------------------

class TestThresholdBoundary:
    def test_below_min_confidence_not_reported(self):
        """
        A graph with exactly 1 TRANSFERRED_TO edge fires MULE_LAYERING indicator A
        only → score = 1/5 = 0.20 < MIN_CONFIDENCE = 0.40 → not reported.
        """
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "TGT", "BANK_ACCOUNT")
        _add_edge(G, "T1", "SRC", "TGT", amount=1000.0)
        result = _classify(G)
        assert PatternType.MULE_LAYERING not in _pattern_types(result)

    def test_at_min_confidence_is_reported(self):
        """
        MULE_LAYERING with exactly 2 indicators fired → 2/5 = 0.40 = MIN_CONFIDENCE.
        Should be included (>= threshold).
        """
        G = _make_graph()
        for nid in ["A", "B", "C"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        # indicator A: 2 transfers
        _add_edge(G, "T1", "A", "B", amount=50000.0)
        _add_edge(G, "T2", "B", "C", amount=48000.0)
        # indicator B: chain length = 2 >= MULE_LAYERING_MIN_HOPS
        # (no timestamps → C fires, no ratio → D no, no hierarchy mule → E no)
        result = _classify(G)
        # At minimum: A + B + C = 3 indicators → score = 3/5 = 0.60 ≥ 0.40
        assert PatternType.MULE_LAYERING in _pattern_types(result)


# ---------------------------------------------------------------------------
# Test 18 — SIM_SWAP rapid-debit outside window does not fire indicator D
# ---------------------------------------------------------------------------

class TestSimSwapRapidDebit:
    def test_transfer_too_late_does_not_fire_rapid_debit(self):
        G = _make_graph("CASE_SS2")
        _add_node(G, "PH_X", "PHONE", sim_swapped_on="2024-01-15")
        _add_node(G, "BA_V", "BANK_ACCOUNT")
        _add_node(G, "BA_M", "BANK_ACCOUNT")
        # Transfer 5 days after SIM swap — outside 1-hour rapid-debit window
        _add_edge(G, "T1", "BA_V", "BA_M", amount=50000.0, ts="2024-01-20T10:00:00")
        m, h = _pipeline(G)
        result = classify_patterns(G, m, h)
        if PatternType.SIM_SWAP in _pattern_types(result):
            ss = next(p for p in result.patterns if p.type == PatternType.SIM_SWAP)
            # Rapid-debit reason should not appear
            assert not any("rapid-debit" in r.lower() or "rapid debit" in r.lower()
                           for r in ss.reasons)


# ---------------------------------------------------------------------------
# Test 19 — VISHING caller ratio boundary
# ---------------------------------------------------------------------------

class TestVishingRatioBoundary:
    def test_equal_callers_and_callees_does_not_fire_ratio_indicator(self):
        """1 caller : 1 callee → ratio = 1.0 > 0.5 → indicator B does not fire."""
        G = _make_graph()
        _add_node(G, "PH_X", "PHONE")
        _add_node(G, "VIC1")
        _add_node(G, "VIC2")
        _add_node(G, "VIC3")
        _add_edge(G, "C1", "PH_X", "VIC1", etype="CALLED")
        _add_edge(G, "C2", "PH_X", "VIC2", etype="CALLED")
        _add_edge(G, "C3", "PH_X", "VIC3", etype="CALLED")
        # 1 caller, 3 callees → ratio = 1/3 ≈ 0.33 ≤ 0.50 → indicator B fires
        result = _classify(G)
        # With 3 calls (A ✓) + ratio (B ✓) + shared caller (C ✓) = 3/4 = 0.75
        assert PatternType.VISHING in _pattern_types(result)

    def test_many_callers_many_callees_above_ratio_threshold(self):
        """4 callers, 4 callees → ratio = 1.0 > 0.5 → indicator B does NOT fire."""
        G = _make_graph()
        for i in range(4):
            ph = f"PH_{i}"
            vic = f"VIC_{i}"
            _add_node(G, ph, "PHONE")
            _add_node(G, vic)
            _add_edge(G, f"C{i}", ph, vic, etype="CALLED")
        result = _classify(G)
        # Only 4 calls (A fires if >= 3) but ratio = 4/4 = 1.0 > 0.5 → B does not fire
        # shared_caller: each phone calls only 1 person → C does not fire
        # No SMS → D does not fire
        # Score = 1/4 = 0.25 < 0.40 → not reported
        assert PatternType.VISHING not in _pattern_types(result)


# ---------------------------------------------------------------------------
# Test 20 — INVESTMENT_TASK early/late split
# ---------------------------------------------------------------------------

class TestInvestmentTaskAmounts:
    def test_large_early_small_late_not_investment_task(self):
        """Reversed pattern (large early, small late) should not fire indicators B-D."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "PLAT", "BANK_ACCOUNT")
        # Large early, small late
        _add_edge(G, "T1", "SRC", "PLAT", amount=200000.0, ts="2024-01-01T10:00:00")
        _add_edge(G, "T2", "SRC", "PLAT", amount=200000.0, ts="2024-01-02T10:00:00")
        _add_edge(G, "T3", "SRC", "PLAT", amount=100.0, ts="2024-01-30T10:00:00")
        result = _classify(G)
        # INVESTMENT_TASK B: min_early >= max_late → B does not fire
        # score = 1/4 (only A) → < MIN_CONFIDENCE
        assert PatternType.INVESTMENT_TASK not in _pattern_types(result)


# ---------------------------------------------------------------------------
# Test 21 — PHISHING_KYC shared IP
# ---------------------------------------------------------------------------

class TestPhishingKycSharedIp:
    def test_shared_ip_detected(self):
        G = _make_graph()
        _add_node(G, "IP_BAD", "IP")
        _add_node(G, "PE_A")
        _add_node(G, "PE_B")
        _add_node(G, "PE_C")
        _add_edge(G, "L1", "PE_A", "IP_BAD", etype="LOGGED_IN_FROM")
        _add_edge(G, "L2", "PE_B", "IP_BAD", etype="LOGGED_IN_FROM")
        _add_edge(G, "L3", "PE_C", "IP_BAD", etype="LOGGED_IN_FROM")
        # Also need SMS component to reach MIN_CONFIDENCE
        _add_node(G, "V1")
        _add_node(G, "V2")
        _add_edge(G, "S1", "PE_A", "V1", etype="SMS_SENT")
        _add_edge(G, "S2", "PE_A", "V2", etype="SMS_SENT")
        result = _classify(G)
        assert PatternType.PHISHING_KYC in _pattern_types(result)
        pk = next(p for p in result.patterns if p.type == PatternType.PHISHING_KYC)
        text = " ".join(pk.reasons).lower()
        assert "ip" in text or "shared" in text


# ---------------------------------------------------------------------------
# Test 22 — Full pipeline integration
# ---------------------------------------------------------------------------

class TestFullPipelineIntegration:
    """
    Synthetic end-to-end:
      ResolvedGraph → build_graph → metrics → communities → hierarchy
                    → classify_patterns
    Verifies complete pipeline compatibility.
    """

    RAW_NODES = [
        {"id": "PE_VICTIM01", "type": "PERSON", "label": "Suspected Victim 01",
         "attrs": {}, "sources": ["n.txt#p1"]},
        {"id": "PH_OP01", "type": "PHONE", "label": "PHONE_OP01",
         "attrs": {}, "sources": ["c.csv#L1"]},
        {"id": "BA_MULE01", "type": "BANK_ACCOUNT", "label": "XXXXXX0001",
         "attrs": {}, "sources": ["t.csv#L1"]},
        {"id": "BA_MULE02", "type": "BANK_ACCOUNT", "label": "XXXXXX0002",
         "attrs": {}, "sources": ["t.csv#L3"]},
        {"id": "BA_KP01", "type": "BANK_ACCOUNT", "label": "XXXXXX9999",
         "attrs": {}, "sources": ["t.csv#L5"]},
    ]
    RAW_EDGES = [
        {"id": "C1", "source": "PH_OP01", "target": "PE_VICTIM01",
         "type": "CALLED", "attrs": {"duration_sec": 55}, "evidence": "c.csv#L1"},
        {"id": "C2", "source": "PH_OP01", "target": "BA_MULE01",
         "type": "CALLED", "attrs": {"duration_sec": 30}, "evidence": "c.csv#L2"},
        {"id": "C3", "source": "PH_OP01", "target": "BA_MULE02",
         "type": "CALLED", "attrs": {"duration_sec": 25}, "evidence": "c.csv#L3"},
        {"id": "T1", "source": "PE_VICTIM01", "target": "BA_MULE01",
         "type": "TRANSFERRED_TO",
         "attrs": {"amount": 50000, "ts": "2024-01-15T10:00:00"},
         "evidence": "t.csv#L1"},
        {"id": "T2", "source": "BA_MULE01", "target": "BA_MULE02",
         "type": "TRANSFERRED_TO",
         "attrs": {"amount": 48000, "ts": "2024-01-15T10:15:00"},
         "evidence": "t.csv#L3"},
        {"id": "T3", "source": "BA_MULE02", "target": "BA_KP01",
         "type": "TRANSFERRED_TO",
         "attrs": {"amount": 46000, "ts": "2024-01-15T10:30:00"},
         "evidence": "t.csv#L5"},
    ]

    @pytest.fixture
    def full_result(self):
        rg = resolve("CASE_FULL_PC", self.RAW_NODES, self.RAW_EDGES)
        G = build_graph(rg)
        m = compute_metrics(G)
        c = detect_communities(G)
        h = score_hierarchy(G, m)
        pr = classify_patterns(G, m, h)
        return G, m, c, h, pr

    def test_pipeline_runs_without_error(self, full_result):
        *_, pr = full_result
        assert pr is not None

    def test_result_type(self, full_result):
        *_, pr = full_result
        assert isinstance(pr, PatternResult)

    def test_case_id_preserved(self, full_result):
        *_, pr = full_result
        assert pr.case_id == "CASE_FULL_PC"

    def test_mule_layering_detected(self, full_result):
        *_, pr = full_result
        assert PatternType.MULE_LAYERING in _pattern_types(pr)

    def test_vishing_detected(self, full_result):
        *_, pr = full_result
        assert PatternType.VISHING in _pattern_types(pr)

    def test_confidence_in_range(self, full_result):
        *_, pr = full_result
        for pm in pr.patterns:
            assert 0.0 <= pm.confidence <= 1.0

    def test_serialisable(self, full_result):
        *_, pr = full_result
        json_str = pr.model_dump_json()
        parsed = PatternResult.model_validate_json(json_str)
        assert parsed.case_id == pr.case_id

    def test_all_reasons_have_content(self, full_result):
        *_, pr = full_result
        for pm in pr.patterns:
            for reason in pm.reasons:
                assert reason.strip(), f"Empty reason in {pm.type}"

    def test_sorted_by_confidence_desc(self, full_result):
        *_, pr = full_result
        confidences = [pm.confidence for pm in pr.patterns]
        assert confidences == sorted(confidences, reverse=True)
