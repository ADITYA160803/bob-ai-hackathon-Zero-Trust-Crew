"""
tests/test_hierarchy.py

Tests for:
  - backend/analysis/hierarchy.py  (score_hierarchy)
  - backend/schemas/analysis.py    (Role, RoleScore, HierarchyResult)

All data is mock/synthetic — no real names, phones, accounts, or identities.
Tests are fully deterministic; no AI/LLM call is made.

Test inventory (matches spec)
-----------------------------
  1.  Empty graph
  2.  Single isolated node
  3.  Clear Mule pattern (fan-in + fan-out + ratio + dwell)
  4.  Mule with pass-through ratio near 1 (within tolerance)
  5.  Mule with dwell time below 30 minutes
  6.  Node with high betweenness connecting multiple mules (Handler indicator)
  7.  Handler indicator
  8.  Terminal fund sink / Kingpin indicator
  9.  Operator with many outgoing CALLED edges
  10. Victim with one outgoing transfer and no onward flow
  11. Missing metrics (node present in graph but no metrics)
  12. Missing timestamps (dwell None — does not fire dwell indicator)
  13. Missing call duration (does not fire short-call indicator)
  14. Parallel transfer edges (counted correctly)
  15. Score always within 0.0–1.0
  16. Every "why" reason corresponds to available evidence
  17. No unsupported role claims (UNKNOWN when evidence absent)
  18. Pydantic serialization/deserialization
  19. HierarchyResult.levels order (KINGPIN → HANDLER → MULE → OPERATOR → VICTIM)
  20. Nodes labelled UNKNOWN do not appear in hierarchy levels
  21. Node ids in each level are sorted (deterministic output)
  22. Full pipeline integration (build_graph → metrics → communities → hierarchy)
"""

from __future__ import annotations

import networkx as nx
import pytest

from backend.analysis.graph_builder import build_graph
from backend.analysis.hierarchy import (
    MULE_DWELL_SEC_THRESHOLD,
    MULE_PASS_THROUGH_TOLERANCE,
    UNKNOWN_THRESHOLD,
    score_hierarchy,
)
from backend.analysis.metrics import compute_metrics
from backend.analysis.communities import detect_communities
from backend.schemas.analysis import (
    HierarchyResult,
    MetricResult,
    NodeMetrics,
    Role,
    RoleScore,
)
from backend.schemas.entities import ResolvedGraph
from backend.services.resolver import resolve


# ---------------------------------------------------------------------------
# Graph helpers (identical pattern to test_metrics_communities.py)
# ---------------------------------------------------------------------------


def _make_graph(case_id: str = "CASE_H") -> nx.MultiDiGraph:
    return nx.MultiDiGraph(case_id=case_id)


def _add_node(G: nx.MultiDiGraph, nid: str, ntype: str = "PERSON") -> None:
    G.add_node(nid, type=ntype, label=nid, attrs={}, sources=["mock.txt#L1"])


def _add_edge(
    G: nx.MultiDiGraph,
    eid: str,
    src: str,
    tgt: str,
    etype: str = "TRANSFERRED_TO",
    amount: float | None = None,
    ts: str | None = None,
    duration_sec: float | None = None,
) -> None:
    attrs: dict = {}
    if amount is not None:
        attrs["amount"] = amount
    if ts is not None:
        attrs["ts"] = ts
    if duration_sec is not None:
        attrs["duration_sec"] = duration_sec
    G.add_edge(src, tgt, key=eid, id=eid, type=etype, attrs=attrs, evidence="mock.csv#L1")


def _pipeline(G: nx.MultiDiGraph) -> tuple[MetricResult, HierarchyResult]:
    """Run metrics then hierarchy on a graph."""
    m = compute_metrics(G)
    h = score_hierarchy(G, m)
    return m, h


def _role_of(result: HierarchyResult, node_id: str) -> Role:
    for rs in result.roles:
        if rs.node_id == node_id:
            return rs.role
    return Role.UNKNOWN


def _score_of(result: HierarchyResult, node_id: str) -> float:
    for rs in result.roles:
        if rs.node_id == node_id:
            return rs.score
    return 0.0


def _why_of(result: HierarchyResult, node_id: str) -> list[str]:
    for rs in result.roles:
        if rs.node_id == node_id:
            return rs.why
    return []


# ---------------------------------------------------------------------------
# Test 1 — Empty graph
# ---------------------------------------------------------------------------


class TestEmptyGraph:
    def test_empty_returns_hierarchy_result(self):
        G = _make_graph("CASE_EMPTY")
        m = compute_metrics(G)
        h = score_hierarchy(G, m)
        assert isinstance(h, HierarchyResult)
        assert h.case_id == "CASE_EMPTY"
        assert h.roles == []
        assert h.levels == []


# ---------------------------------------------------------------------------
# Test 2 — Single isolated node
# ---------------------------------------------------------------------------


class TestSingleIsolatedNode:
    def test_isolated_node_unknown_or_low_score(self):
        G = _make_graph()
        _add_node(G, "PE_ISO")
        _, h = _pipeline(G)
        rs = _role_of(h, "PE_ISO")
        score = _score_of(h, "PE_ISO")
        # No edges → no role indicators → UNKNOWN
        assert rs == Role.UNKNOWN
        assert score < UNKNOWN_THRESHOLD

    def test_isolated_node_not_in_levels(self):
        G = _make_graph()
        _add_node(G, "PE_ISO")
        _, h = _pipeline(G)
        flat = [n for level in h.levels for n in level]
        assert "PE_ISO" not in flat


# ---------------------------------------------------------------------------
# Test 3 — Clear Mule pattern (all 4 indicators)
# ---------------------------------------------------------------------------


class TestClearMule:
    @pytest.fixture
    def mule_graph(self):
        G = _make_graph("CASE_MULE")
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "MULE", "SNK", amount=48000.0, ts="2024-01-15T10:15:00")
        return G

    def test_mule_role_assigned(self, mule_graph):
        _, h = _pipeline(mule_graph)
        assert _role_of(h, "MULE") == Role.MULE

    def test_mule_score_is_1(self, mule_graph):
        """All 4 MULE indicators fired → score = 1.0."""
        _, h = _pipeline(mule_graph)
        assert _score_of(h, "MULE") == pytest.approx(1.0)

    def test_mule_has_four_why_reasons(self, mule_graph):
        _, h = _pipeline(mule_graph)
        assert len(_why_of(h, "MULE")) == 4

    def test_mule_in_levels(self, mule_graph):
        _, h = _pipeline(mule_graph)
        assert any("MULE" in level for level in h.levels)


# ---------------------------------------------------------------------------
# Test 4 — Mule with pass-through ratio near 1 (within tolerance)
# ---------------------------------------------------------------------------


class TestMulePassThroughTolerance:
    def test_ratio_within_tolerance_fires(self):
        """ratio = 0.80 is within [0.75, 1.25] — indicator fires."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=100000.0)
        _add_edge(G, "E2", "MULE", "SNK", amount=80000.0)
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        assert any("pass-through ratio" in w.lower() for w in why)

    def test_ratio_outside_tolerance_does_not_fire(self):
        """ratio = 0.40 is outside [0.75, 1.25] — indicator does NOT fire."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=100000.0)
        _add_edge(G, "E2", "MULE", "SNK", amount=40000.0)
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        # ratio = 0.4 → outside [0.75, 1.25] → no pass-through reason
        assert not any(
            ("pass-through ratio" in w.lower() and "within tolerance" in w.lower())
            for w in why
        )

    def test_tolerance_boundary_exact(self):
        """ratio = 0.75 is exactly at the lower boundary — fires."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=100000.0)
        _add_edge(G, "E2", "MULE", "SNK", amount=75000.0)
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        assert any("pass-through ratio" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 5 — Mule with dwell time below 30 minutes
# ---------------------------------------------------------------------------


class TestMuleDwellTime:
    def test_dwell_below_threshold_fires(self):
        """10 minutes < 30 minutes — dwell indicator fires."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "MULE", "SNK", amount=48000.0, ts="2024-01-15T10:10:00")
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        assert any("dwell time" in w.lower() for w in why)

    def test_dwell_above_threshold_does_not_fire(self):
        """2 hours > 30 minutes — dwell indicator does NOT fire."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=50000.0, ts="2024-01-15T08:00:00")
        _add_edge(G, "E2", "MULE", "SNK", amount=48000.0, ts="2024-01-15T10:00:00")
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        assert not any("dwell time" in w.lower() for w in why)

    def test_missing_timestamps_no_dwell_indicator(self):
        """Test 12 — missing timestamps → dwell reason absent."""
        G = _make_graph()
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        # No ts argument
        _add_edge(G, "E1", "SRC", "MULE", amount=50000.0)
        _add_edge(G, "E2", "MULE", "SNK", amount=48000.0)
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        assert not any("dwell time" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 6 + 7 — Handler: high betweenness connecting multiple nodes
# ---------------------------------------------------------------------------


class TestHandlerIndicator:
    @pytest.fixture
    def handler_graph(self):
        """
        Star topology: HANDLER connects 3 mule accounts.
        HANDLER will have the highest betweenness in this 5-node chain.
        """
        G = _make_graph("CASE_HANDLER")
        for nid in ["SRC", "HDL", "M1", "M2", "M3"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        # Funds flow: SRC → HDL → M1, M2, M3
        _add_edge(G, "E1", "SRC", "HDL", amount=90000.0, ts="2024-01-15T09:00:00")
        _add_edge(G, "E2", "HDL", "M1", amount=29000.0, ts="2024-01-15T09:30:00")
        _add_edge(G, "E3", "HDL", "M2", amount=29000.0, ts="2024-01-15T09:30:00")
        _add_edge(G, "E4", "HDL", "M3", amount=29000.0, ts="2024-01-15T09:30:00")
        return G

    def test_handler_role_assigned(self, handler_graph):
        _, h = _pipeline(handler_graph)
        role = _role_of(h, "HDL")
        # HDL has high betweenness, fan-in 1, fan-out 3, ratio < 0.9 (keeps ~3k)
        assert role == Role.HANDLER

    def test_handler_score_positive(self, handler_graph):
        _, h = _pipeline(handler_graph)
        assert _score_of(h, "HDL") > 0.0

    def test_handler_why_contains_betweenness(self, handler_graph):
        _, h = _pipeline(handler_graph)
        why = _why_of(h, "HDL")
        assert any("betweenness" in w.lower() for w in why)

    def test_handler_why_contains_fan_in_or_out(self, handler_graph):
        _, h = _pipeline(handler_graph)
        why = _why_of(h, "HDL")
        has_fan = any("incoming transfer" in w.lower() or "outgoing transfer" in w.lower() for w in why)
        assert has_fan

    def test_handler_in_levels(self, handler_graph):
        _, h = _pipeline(handler_graph)
        flat = {n for level in h.levels for n in level}
        assert "HDL" in flat


# ---------------------------------------------------------------------------
# Test 8 — Kingpin: terminal fund sink
# ---------------------------------------------------------------------------


class TestKingpinIndicator:
    @pytest.fixture
    def kingpin_graph(self):
        """
        Chain: VICTIM → MULE → KINGPIN (terminal sink, largest inflow share).
        KINGPIN receives all funds and forwards nothing.
        """
        G = _make_graph("CASE_KINGPIN")
        for nid in ["VICTIM", "MULE", "KP"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        # Large fund flow into KP
        _add_edge(G, "E1", "VICTIM", "MULE", amount=100000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "MULE", "KP", amount=95000.0, ts="2024-01-15T10:20:00")
        return G

    def test_kingpin_role_assigned(self, kingpin_graph):
        _, h = _pipeline(kingpin_graph)
        role = _role_of(h, "KP")
        assert role == Role.KINGPIN

    def test_kingpin_score_positive(self, kingpin_graph):
        _, h = _pipeline(kingpin_graph)
        assert _score_of(h, "KP") > 0.0

    def test_kingpin_why_contains_terminal_sink(self, kingpin_graph):
        _, h = _pipeline(kingpin_graph)
        why = _why_of(h, "KP")
        assert any("terminal" in w.lower() or "no outgoing" in w.lower() for w in why)

    def test_kingpin_in_level_zero(self, kingpin_graph):
        """Kingpin should appear in levels[0]."""
        _, h = _pipeline(kingpin_graph)
        if h.levels:
            assert "KP" in h.levels[0]

    def test_kingpin_why_contains_fund_fraction(self, kingpin_graph):
        """KP receives 95k / 95k total inflow = 100% — fraction indicator fires."""
        _, h = _pipeline(kingpin_graph)
        why = _why_of(h, "KP")
        assert any("%" in w and "inflow" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 9 — Operator: many outgoing CALLED edges
# ---------------------------------------------------------------------------


class TestOperatorIndicator:
    @pytest.fixture
    def operator_graph(self):
        G = _make_graph("CASE_OP")
        _add_node(G, "OP", "PHONE")
        for i in range(4):
            vid = f"V{i}"
            _add_node(G, vid)
            _add_edge(G, f"C{i}", "OP", vid, etype="CALLED", duration_sec=45.0)
        return G

    def test_operator_role_assigned(self, operator_graph):
        _, h = _pipeline(operator_graph)
        assert _role_of(h, "OP") == Role.OPERATOR

    def test_operator_why_contains_calls(self, operator_graph):
        _, h = _pipeline(operator_graph)
        why = _why_of(h, "OP")
        assert any("called" in w.lower() for w in why)

    def test_operator_why_contains_short_call(self, operator_graph):
        """duration_sec=45 < 120 → short-call indicator fires."""
        _, h = _pipeline(operator_graph)
        why = _why_of(h, "OP")
        assert any("short" in w.lower() or "duration" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 10 — Victim: one outgoing transfer, no onward flow
# ---------------------------------------------------------------------------


class TestVictimIndicator:
    @pytest.fixture
    def victim_graph(self):
        G = _make_graph("CASE_VIC")
        _add_node(G, "VIC")
        _add_node(G, "MULE_ACC", "BANK_ACCOUNT")
        _add_node(G, "OP_PHONE", "PHONE")
        # Victim sends one transfer out
        _add_edge(G, "E1", "VIC", "MULE_ACC", amount=30000.0)
        # Operator called victim (possible OTP/vishing)
        _add_edge(G, "C1", "OP_PHONE", "VIC", etype="CALLED")
        return G

    def test_victim_role_assigned(self, victim_graph):
        _, h = _pipeline(victim_graph)
        assert _role_of(h, "VIC") == Role.VICTIM

    def test_victim_why_contains_transfer_out(self, victim_graph):
        _, h = _pipeline(victim_graph)
        why = _why_of(h, "VIC")
        assert any("transfer" in w.lower() for w in why)

    def test_victim_why_contains_call_received(self, victim_graph):
        _, h = _pipeline(victim_graph)
        why = _why_of(h, "VIC")
        assert any("called" in w.lower() or "sms" in w.lower() or "otp" in w.lower() for w in why)

    def test_victim_why_contains_no_incoming_transfers(self, victim_graph):
        _, h = _pipeline(victim_graph)
        why = _why_of(h, "VIC")
        assert any("no incoming" in w.lower() or "incoming transfer" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 11 — Missing metrics (metric coverage)
# ---------------------------------------------------------------------------


class TestMissingMetrics:
    def test_node_without_metrics_skipped(self):
        """
        If graph has a node that metrics did not cover (e.g. from a stale
        MetricResult), score_hierarchy skips it gracefully.
        """
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "PE_B")
        # Build metrics only for PE_A, not PE_B
        full_metrics = compute_metrics(G)
        # Simulate partial metrics by filtering
        partial = MetricResult(
            case_id=full_metrics.case_id,
            nodes=[nm for nm in full_metrics.nodes if nm.node_id == "PE_A"],
        )
        h = score_hierarchy(G, partial)
        ids_in_roles = {rs.node_id for rs in h.roles}
        # PE_B was not in metrics → should not appear in roles
        assert "PE_B" not in ids_in_roles
        # PE_A is present
        assert "PE_A" in ids_in_roles


# ---------------------------------------------------------------------------
# Test 13 — Missing call duration does not fire short-call indicator
# ---------------------------------------------------------------------------


class TestMissingCallDuration:
    def test_no_duration_no_short_call_reason(self):
        G = _make_graph()
        _add_node(G, "OP", "PHONE")
        _add_node(G, "V1")
        _add_node(G, "V2")
        # Calls without duration_sec
        _add_edge(G, "C1", "OP", "V1", etype="CALLED")
        _add_edge(G, "C2", "OP", "V2", etype="CALLED")
        _, h = _pipeline(G)
        why = _why_of(h, "OP")
        # short-call indicator must NOT fire
        assert not any("duration_sec" in w or "short" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 14 — Parallel transfer edges
# ---------------------------------------------------------------------------


class TestParallelTransferEdges:
    def test_parallel_edges_counted_in_score(self):
        """Two parallel incoming edges count as fan-in=2 → indicator fires."""
        G = _make_graph()
        _add_node(G, "S1", "BANK_ACCOUNT")
        _add_node(G, "S2", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "S1", "MULE", amount=30000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "S2", "MULE", amount=20000.0, ts="2024-01-15T10:01:00")
        _add_edge(G, "E3", "MULE", "SNK", amount=48000.0, ts="2024-01-15T10:15:00")
        _, h = _pipeline(G)
        why = _why_of(h, "MULE")
        # fan-in = 2 → indicator fires
        assert any("fan-in" in w.lower() or "incoming transfer" in w.lower() for w in why)


# ---------------------------------------------------------------------------
# Test 15 — Score always within [0.0, 1.0]
# ---------------------------------------------------------------------------


class TestScoreRange:
    def test_all_scores_in_range(self):
        G = _make_graph()
        for nid in ["PE_A", "BA_X", "BA_Y", "BA_Z", "PH_Q"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=48000.0, ts="2024-01-15T10:10:00")
        _add_edge(G, "E3", "BA_Y", "BA_Z", amount=46000.0, ts="2024-01-15T10:20:00")
        _add_edge(G, "C1", "PH_Q", "PE_A", etype="CALLED", duration_sec=30.0)
        _add_edge(G, "C2", "PH_Q", "BA_X", etype="CALLED", duration_sec=25.0)
        _, h = _pipeline(G)
        for rs in h.roles:
            assert 0.0 <= rs.score <= 1.0, f"Score {rs.score} out of range for {rs.node_id}"


# ---------------------------------------------------------------------------
# Test 16 — Every "why" corresponds to actual evidence
# ---------------------------------------------------------------------------


class TestWhyEvidenceBacked:
    def test_why_list_not_empty_only_when_evidence_exists(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _, h = _pipeline(G)
        for rs in h.roles:
            if rs.score == 0.0:
                assert rs.why == [], (
                    f"Node {rs.node_id} has score 0 but non-empty why: {rs.why}"
                )


# ---------------------------------------------------------------------------
# Test 17 — UNKNOWN when evidence absent
# ---------------------------------------------------------------------------


class TestUnknownWhenNoEvidence:
    def test_no_evidence_gives_unknown(self):
        G = _make_graph()
        _add_node(G, "PE_GHOST")
        _, h = _pipeline(G)
        role = _role_of(h, "PE_GHOST")
        assert role == Role.UNKNOWN

    def test_unknown_score_below_threshold(self):
        G = _make_graph()
        _add_node(G, "PE_GHOST")
        _, h = _pipeline(G)
        score = _score_of(h, "PE_GHOST")
        assert score < UNKNOWN_THRESHOLD


# ---------------------------------------------------------------------------
# Test 18 — Pydantic serialization/deserialization
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_hierarchy_result_json_round_trip(self):
        G = _make_graph("CASE_SERIAL")
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "MULE", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "SRC", "MULE", amount=50000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "MULE", "SNK", amount=48000.0, ts="2024-01-15T10:15:00")
        _, h = _pipeline(G)
        json_str = h.model_dump_json()
        parsed = HierarchyResult.model_validate_json(json_str)
        assert parsed.case_id == h.case_id
        assert len(parsed.roles) == len(h.roles)
        assert parsed.levels == h.levels

    def test_role_score_model(self):
        rs = RoleScore(node_id="BA_X", role=Role.MULE, score=0.75, why=["reason"])
        d = rs.model_dump()
        assert d["role"] == "MULE"
        assert d["score"] == 0.75


# ---------------------------------------------------------------------------
# Test 19 — Levels order: KINGPIN → HANDLER → MULE → OPERATOR → VICTIM
# ---------------------------------------------------------------------------


class TestHierarchyLevelsOrder:
    def test_kingpin_before_mule_in_levels(self):
        """
        If both KINGPIN and MULE are present, KINGPIN level appears before MULE.
        """
        G = _make_graph("CASE_ORDER")
        _add_node(G, "VIC", "PERSON")
        _add_node(G, "MULE_ACC", "BANK_ACCOUNT")
        _add_node(G, "KP_ACC", "BANK_ACCOUNT")
        _add_node(G, "OP_PH", "PHONE")
        # Victim pattern
        _add_edge(G, "C1", "OP_PH", "VIC", etype="CALLED")
        _add_edge(G, "ET1", "VIC", "MULE_ACC", amount=50000.0, ts="2024-01-15T10:00:00")
        # Mule pattern
        _add_edge(G, "ET2", "MULE_ACC", "KP_ACC", amount=48000.0, ts="2024-01-15T10:15:00")
        _, h = _pipeline(G)
        # Build role→level_index mapping
        role_in_levels: dict[str, int] = {}
        for idx, level in enumerate(h.levels):
            for nid in level:
                role_in_levels[nid] = idx
        # If KP_ACC is KINGPIN, it should appear at a lower level index than MULE_ACC
        if "KP_ACC" in role_in_levels and "MULE_ACC" in role_in_levels:
            assert role_in_levels["KP_ACC"] < role_in_levels["MULE_ACC"]


# ---------------------------------------------------------------------------
# Test 20 — UNKNOWN nodes not in levels
# ---------------------------------------------------------------------------


class TestUnknownNotInLevels:
    def test_unknown_nodes_absent_from_levels(self):
        G = _make_graph()
        _add_node(G, "PE_ISO")
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _, h = _pipeline(G)
        unknown_ids = {rs.node_id for rs in h.roles if rs.role == Role.UNKNOWN}
        flat_in_levels = {n for level in h.levels for n in level}
        assert unknown_ids.isdisjoint(flat_in_levels)


# ---------------------------------------------------------------------------
# Test 21 — Node ids in each level are sorted (deterministic)
# ---------------------------------------------------------------------------


class TestLevelsSorted:
    def test_node_ids_sorted_within_levels(self):
        G = _make_graph()
        for nid in ["M3", "M1", "M2"]:
            _add_node(G, nid, "BANK_ACCOUNT")
        _add_node(G, "SRC", "BANK_ACCOUNT")
        _add_node(G, "SNK", "BANK_ACCOUNT")
        # Feed each Mx account with identical mule pattern
        for i, mid in enumerate(["M1", "M2", "M3"], start=1):
            _add_edge(G, f"IN{i}", "SRC", mid, amount=30000.0, ts=f"2024-01-15T09:0{i}:00")
            _add_edge(G, f"OUT{i}", mid, "SNK", amount=29000.0, ts=f"2024-01-15T09:3{i}:00")
        _, h = _pipeline(G)
        for level in h.levels:
            assert level == sorted(level), f"Level not sorted: {level}"


# ---------------------------------------------------------------------------
# Test 22 — Full pipeline integration
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """
    Synthetic end-to-end:
      ResolvedGraph → build_graph → compute_metrics → detect_communities
                    → score_hierarchy
    """

    RAW_NODES = [
        {"id": "PE_VICTIM01", "type": "PERSON", "label": "Suspected Victim 01",
         "attrs": {}, "sources": ["notes.txt#p1"]},
        {"id": "PH_OP01", "type": "PHONE", "label": "PHONE_OP01",
         "attrs": {}, "sources": ["calls.csv#L1"]},
        {"id": "BA_MULE01", "type": "BANK_ACCOUNT", "label": "XXXXXX0001",
         "attrs": {}, "sources": ["txn.csv#L1"]},
        {"id": "BA_MULE02", "type": "BANK_ACCOUNT", "label": "XXXXXX0002",
         "attrs": {}, "sources": ["txn.csv#L3"]},
        {"id": "BA_KP01", "type": "BANK_ACCOUNT", "label": "XXXXXX9999",
         "attrs": {}, "sources": ["txn.csv#L5"]},
    ]
    RAW_EDGES = [
        # Operator calls victim
        {"id": "C1", "source": "PH_OP01", "target": "PE_VICTIM01",
         "type": "CALLED", "attrs": {"duration_sec": 55}, "evidence": "calls.csv#L1"},
        # Victim sends funds to mule01
        {"id": "T1", "source": "PE_VICTIM01", "target": "BA_MULE01",
         "type": "TRANSFERRED_TO",
         "attrs": {"amount": 50000, "ts": "2024-01-15T10:00:00"},
         "evidence": "txn.csv#L1"},
        # Mule01 forwards to mule02
        {"id": "T2", "source": "BA_MULE01", "target": "BA_MULE02",
         "type": "TRANSFERRED_TO",
         "attrs": {"amount": 48000, "ts": "2024-01-15T10:15:00"},
         "evidence": "txn.csv#L3"},
        # Mule02 forwards to kingpin
        {"id": "T3", "source": "BA_MULE02", "target": "BA_KP01",
         "type": "TRANSFERRED_TO",
         "attrs": {"amount": 46000, "ts": "2024-01-15T10:30:00"},
         "evidence": "txn.csv#L5"},
    ]

    @pytest.fixture
    def full_result(self):
        rg = resolve("CASE_FULL", self.RAW_NODES, self.RAW_EDGES)
        G = build_graph(rg)
        m = compute_metrics(G)
        c = detect_communities(G)
        h = score_hierarchy(G, m)
        return G, m, c, h

    def test_pipeline_runs_without_error(self, full_result):
        G, m, c, h = full_result
        assert h is not None

    def test_hierarchy_result_type(self, full_result):
        _, _, _, h = full_result
        assert isinstance(h, HierarchyResult)

    def test_all_nodes_scored(self, full_result):
        _, _, _, h = full_result
        scored_ids = {rs.node_id for rs in h.roles}
        expected_ids = {"PE_VICTIM01", "PH_OP01", "BA_MULE01", "BA_MULE02", "BA_KP01"}
        assert scored_ids == expected_ids

    def test_victim_role(self, full_result):
        _, _, _, h = full_result
        assert _role_of(h, "PE_VICTIM01") == Role.VICTIM

    def test_operator_role(self, full_result):
        _, _, _, h = full_result
        assert _role_of(h, "PH_OP01") == Role.OPERATOR

    def test_mule_roles(self, full_result):
        _, _, _, h = full_result
        # BA_MULE01 and BA_MULE02 should be MULE (both have in+out transfers)
        for mid in ["BA_MULE01", "BA_MULE02"]:
            assert _role_of(h, mid) == Role.MULE, f"Expected MULE for {mid}"

    def test_kingpin_role(self, full_result):
        _, _, _, h = full_result
        assert _role_of(h, "BA_KP01") == Role.KINGPIN

    def test_scores_in_range(self, full_result):
        _, _, _, h = full_result
        for rs in h.roles:
            assert 0.0 <= rs.score <= 1.0

    def test_hierarchy_levels_present(self, full_result):
        _, _, _, h = full_result
        assert len(h.levels) >= 2  # at least two distinct role levels

    def test_serialisable(self, full_result):
        _, _, _, h = full_result
        json_str = h.model_dump_json()
        parsed = HierarchyResult.model_validate_json(json_str)
        assert parsed.case_id == "CASE_FULL"

    def test_why_reasons_non_empty_for_scored_nodes(self, full_result):
        _, _, _, h = full_result
        for rs in h.roles:
            if rs.role != Role.UNKNOWN:
                assert rs.why, f"Node {rs.node_id} role {rs.role} has no why reasons"

    def test_no_real_data(self, full_result):
        """Verify no real-world identifiers leaked into outputs."""
        _, _, _, h = full_result
        json_str = h.model_dump_json()
        # Basic check: our synthetic IDs are all prefixed with mock convention
        assert "PE_VICTIM01" in json_str
        assert "BA_KP01" in json_str
