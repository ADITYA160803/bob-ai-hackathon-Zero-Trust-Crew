"""
tests/test_metrics_communities.py

Tests for:
  - backend/analysis/metrics.py   (compute_metrics)
  - backend/analysis/communities.py (detect_communities)
  - backend/schemas/analysis.py   (NodeMetrics, MetricResult, Community, CommunityResult)

All data is mock/synthetic — no real phone numbers, accounts, or identities.
Tests are fully deterministic; no AI/LLM call is made.

Test inventory
--------------
METRICS
  1.  empty graph
  2.  single node
  3.  basic directed graph — node count, return type
  4.  multiple incoming edges — fan-in counted correctly
  5.  multiple outgoing edges — fan-out counted correctly
  6.  parallel transfer edges — both edges counted independently
  7.  degree centrality — values in [0, 1]
  8.  betweenness centrality — values >= 0
  9.  transfer fan-in count
  10. transfer fan-out count
  11. pass-through ratio — normal case
  12. zero incoming-flow — ratio is None
  13. transfer dwell time — basic case
  14. missing timestamp — dwell time is None (not fabricated)
  15. multiple transfers — minimum dwell chosen
  16. malformed/invalid timestamp — skipped, dwell None if no valid ts remains
  17. non-TRANSFERRED_TO edges excluded from transfer metrics
  18. in_amount / out_amount sums correct
  19. pass-through ratio exact value
  20. MetricResult is Pydantic-serialisable (JSON round-trip)

COMMUNITIES
  21. empty graph — empty CommunityResult
  22. one connected community
  23. multiple disconnected communities
  24. parallel edges do not duplicate nodes in community
  25. community node IDs preserved
  26. community sizes correct
  27. communities sorted by size descending
  28. CommunityResult is Pydantic-serialisable (JSON round-trip)
  29. method field is correct string
"""

from __future__ import annotations

import json
from datetime import timezone

import networkx as nx
import pytest

from backend.analysis.communities import detect_communities
from backend.analysis.graph_builder import build_graph
from backend.analysis.metrics import compute_metrics, _parse_ts
from backend.schemas.analysis import (
    Community,
    CommunityResult,
    MetricResult,
    NodeMetrics,
)
from backend.schemas.entities import ResolvedGraph
from backend.services.resolver import resolve


# ---------------------------------------------------------------------------
# Helpers — build test graphs directly (bypass resolver for speed)
# ---------------------------------------------------------------------------


def _make_graph(case_id: str = "CASE_TEST") -> nx.MultiDiGraph:
    """Return an empty MultiDiGraph with a case_id."""
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
) -> None:
    attrs: dict = {}
    if amount is not None:
        attrs["amount"] = amount
    if ts is not None:
        attrs["ts"] = ts
    G.add_edge(src, tgt, key=eid, id=eid, type=etype, attrs=attrs, evidence="mock.csv#L1")


# ---------------------------------------------------------------------------
# METRICS TESTS
# ---------------------------------------------------------------------------


class TestMetricsEmpty:
    """Test 1 — empty graph."""

    def test_empty_graph_returns_metric_result(self):
        G = _make_graph("CASE_EMPTY")
        result = compute_metrics(G)
        assert isinstance(result, MetricResult)
        assert result.case_id == "CASE_EMPTY"
        assert result.nodes == []


class TestMetricsSingleNode:
    """Test 2 — single node."""

    def test_single_node(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        result = compute_metrics(G)
        assert len(result.nodes) == 1
        nm = result.nodes[0]
        assert nm.node_id == "PE_A"
        assert nm.in_degree == 0
        assert nm.out_degree == 0
        assert nm.transfer_fan_in == 0
        assert nm.transfer_fan_out == 0
        assert nm.pass_through_ratio is None
        assert nm.min_dwell_sec is None
        # NetworkX degree_centrality returns 1.0 for a single-node graph
        # (normalisation by (n-1) = 0 is handled internally — result is 1.0)
        assert nm.degree_centrality == pytest.approx(1.0)
        assert nm.betweenness == 0.0


class TestMetricsBasicGraph:
    """Test 3 — basic directed graph; return type and node count."""

    @pytest.fixture
    def basic_graph(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        _add_node(G, "BA_Y", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0, ts="2024-01-01T10:00:00")
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=45000.0, ts="2024-01-01T10:20:00")
        return G

    def test_returns_metric_result(self, basic_graph):
        result = compute_metrics(basic_graph)
        assert isinstance(result, MetricResult)

    def test_node_count(self, basic_graph):
        result = compute_metrics(basic_graph)
        assert len(result.nodes) == 3

    def test_all_node_ids_present(self, basic_graph):
        result = compute_metrics(basic_graph)
        ids = {nm.node_id for nm in result.nodes}
        assert ids == {"PE_A", "BA_X", "BA_Y"}


class TestFanIn:
    """Tests 4, 9 — multiple incoming edges; transfer fan-in."""

    def test_multiple_incoming_edges(self):
        G = _make_graph()
        _add_node(G, "BA_MULE", "BANK_ACCOUNT")
        _add_node(G, "PE_SRC1")
        _add_node(G, "PE_SRC2")
        _add_edge(G, "E1", "PE_SRC1", "BA_MULE", amount=10000.0)
        _add_edge(G, "E2", "PE_SRC2", "BA_MULE", amount=20000.0)
        result = compute_metrics(G)
        mule = next(nm for nm in result.nodes if nm.node_id == "BA_MULE")
        assert mule.in_degree == 2
        assert mule.transfer_fan_in == 2

    def test_transfer_fan_in_counts_only_transfer_edges(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        # OWNS edge — should NOT count in transfer_fan_in
        _add_edge(G, "E1", "PE_A", "BA_X", etype="OWNS")
        # TRANSFERRED_TO — should count
        _add_edge(G, "E2", "PE_A", "BA_X", amount=5000.0)
        result = compute_metrics(G)
        ba = next(nm for nm in result.nodes if nm.node_id == "BA_X")
        assert ba.in_degree == 2   # both edges
        assert ba.transfer_fan_in == 1   # only transfer


class TestFanOut:
    """Tests 5, 10 — multiple outgoing edges; transfer fan-out."""

    def test_multiple_outgoing_edges(self):
        G = _make_graph()
        _add_node(G, "PE_OP", "PERSON")
        _add_node(G, "PE_V1")
        _add_node(G, "PE_V2")
        _add_edge(G, "E1", "PE_OP", "PE_V1", etype="CALLED")
        _add_edge(G, "E2", "PE_OP", "PE_V2", etype="CALLED")
        result = compute_metrics(G)
        op = next(nm for nm in result.nodes if nm.node_id == "PE_OP")
        assert op.out_degree == 2

    def test_transfer_fan_out_counts_only_transfer_edges(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        _add_node(G, "BA_Y", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A", "BA_X", etype="OWNS")
        _add_edge(G, "E2", "PE_A", "BA_Y", amount=5000.0)
        result = compute_metrics(G)
        pe = next(nm for nm in result.nodes if nm.node_id == "PE_A")
        assert pe.transfer_fan_out == 1


class TestParallelTransferEdges:
    """Test 6 — parallel transfer edges counted independently."""

    def test_parallel_edges_both_counted(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        # Two separate evidenced transfers between same pair
        _add_edge(G, "E1", "PE_A", "BA_X", amount=30000.0, ts="2024-01-01T09:00:00")
        _add_edge(G, "E2", "PE_A", "BA_X", amount=20000.0, ts="2024-01-01T09:05:00")
        result = compute_metrics(G)
        pe = next(nm for nm in result.nodes if nm.node_id == "PE_A")
        assert pe.transfer_fan_out == 2
        assert pe.out_amount == 50000.0   # 30000 + 20000

    def test_parallel_in_edges_summed(self):
        G = _make_graph()
        _add_node(G, "PE_SRC")
        _add_node(G, "BA_MULE", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_SRC", "BA_MULE", amount=40000.0)
        _add_edge(G, "E2", "PE_SRC", "BA_MULE", amount=10000.0)
        result = compute_metrics(G)
        mule = next(nm for nm in result.nodes if nm.node_id == "BA_MULE")
        assert mule.transfer_fan_in == 2
        assert mule.in_amount == 50000.0


class TestDegreeCentrality:
    """Test 7 — degree centrality values >= 0 (may exceed 1 for MultiDiGraph parallel edges)."""

    def test_degree_centrality_non_negative(self):
        """On a MultiDiGraph, degree_centrality >= 0 always; may exceed 1.0 with parallel edges."""
        G = _make_graph()
        for nid in ["PE_A", "BA_X", "BA_Y", "PE_V"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=45000.0)
        result = compute_metrics(G)
        for nm in result.nodes:
            assert nm.degree_centrality >= 0.0

    def test_degree_centrality_hub_higher(self):
        """The hub node (BA_X with 2 connections) should have higher centrality than PE_V (0)."""
        G = _make_graph()
        for nid in ["PE_A", "BA_X", "BA_Y", "PE_V"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=45000.0)
        result = compute_metrics(G)
        metrics_by_id = {nm.node_id: nm for nm in result.nodes}
        assert metrics_by_id["BA_X"].degree_centrality > metrics_by_id["PE_V"].degree_centrality


class TestBetweennessCentrality:
    """Test 8 — betweenness centrality >= 0."""

    def test_betweenness_non_negative(self):
        G = _make_graph()
        for nid in ["PE_A", "BA_X", "BA_Y"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=45000.0)
        result = compute_metrics(G)
        for nm in result.nodes:
            assert nm.betweenness >= 0.0

    def test_betweenness_intermediary_higher(self):
        """BA_X sits between PE_A and BA_Y — should have highest betweenness."""
        G = _make_graph()
        for nid in ["PE_A", "BA_X", "BA_Y"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=45000.0)
        result = compute_metrics(G)
        m = {nm.node_id: nm for nm in result.nodes}
        assert m["BA_X"].betweenness >= m["PE_A"].betweenness
        assert m["BA_X"].betweenness >= m["BA_Y"].betweenness


class TestPassThroughRatio:
    """Tests 11, 12, 19 — pass-through ratio."""

    def test_normal_pass_through(self):
        """Node receives 50k, forwards 45k → ratio ≈ 0.9."""
        G = _make_graph()
        _add_node(G, "PE_SRC")
        _add_node(G, "BA_MULE", "BANK_ACCOUNT")
        _add_node(G, "BA_SINK", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_SRC", "BA_MULE", amount=50000.0)
        _add_edge(G, "E2", "BA_MULE", "BA_SINK", amount=45000.0)
        result = compute_metrics(G)
        mule = next(nm for nm in result.nodes if nm.node_id == "BA_MULE")
        assert mule.pass_through_ratio is not None
        assert abs(mule.pass_through_ratio - 0.9) < 1e-9

    def test_zero_incoming_gives_none(self):
        """Test 12 — no incoming transfers → ratio must be None."""
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A", "BA_X", amount=10000.0)
        result = compute_metrics(G)
        pe = next(nm for nm in result.nodes if nm.node_id == "PE_A")
        assert pe.pass_through_ratio is None  # no incoming transfers

    def test_exact_pass_through_value(self):
        """Test 19 — exact ratio = 45000/50000 = 0.9."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC", "MID", amount=50000.0)
        _add_edge(G, "E2", "MID", "SNK", amount=45000.0)
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.pass_through_ratio == pytest.approx(0.9)

    def test_mule_pass_through_near_one(self):
        """Mule indicator: pass-through ratio ≈ 1.0."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MULE")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC", "MULE", amount=100000.0)
        _add_edge(G, "E2", "MULE", "SNK", amount=99500.0)
        result = compute_metrics(G)
        mule = next(nm for nm in result.nodes if nm.node_id == "MULE")
        assert mule.pass_through_ratio == pytest.approx(0.995)

    def test_no_amount_field_gives_none(self):
        """Edges without 'amount' in attrs → in_amount is None → ratio None."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        # No amount kwarg — attrs will be empty
        _add_edge(G, "E1", "SRC", "MID")
        _add_edge(G, "E2", "MID", "SNK")
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.in_amount is None
        assert mid.out_amount is None
        assert mid.pass_through_ratio is None


class TestDwellTime:
    """Tests 13, 14, 15, 16 — transfer dwell time."""

    def test_basic_dwell_time(self):
        """Test 13 — 20-minute gap (1200 seconds)."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC", "MID", amount=10000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "MID", "SNK", amount=9000.0, ts="2024-01-15T10:20:00")
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.min_dwell_sec == pytest.approx(1200.0)

    def test_missing_timestamp_gives_none(self):
        """Test 14 — edge without 'ts' → dwell time is None."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        # No ts kwarg
        _add_edge(G, "E1", "SRC", "MID", amount=10000.0)
        _add_edge(G, "E2", "MID", "SNK", amount=9000.0)
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.min_dwell_sec is None

    def test_multiple_transfers_minimum_dwell(self):
        """Test 15 — minimum of multiple valid gaps is returned."""
        G = _make_graph()
        _add_node(G, "SRC1")
        _add_node(G, "SRC2")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        # Two incoming: at T+0 and T+60
        _add_edge(G, "E1", "SRC1", "MID", amount=10000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E2", "SRC2", "MID", amount=10000.0, ts="2024-01-15T10:01:00")
        # One outgoing: at T+15 min
        _add_edge(G, "E3", "MID", "SNK", amount=19000.0, ts="2024-01-15T10:15:00")
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        # Gaps: E1→E3 = 15min=900s; E2→E3 = 14min=840s  → minimum = 840s
        assert mid.min_dwell_sec == pytest.approx(840.0)

    def test_malformed_timestamp_skipped(self):
        """Test 16 — invalid timestamp string is skipped; dwell None if no valid remain."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC", "MID", amount=10000.0, ts="NOT_A_DATE")
        _add_edge(G, "E2", "MID", "SNK", amount=9000.0, ts="ALSO_BAD")
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.min_dwell_sec is None

    def test_malformed_and_valid_timestamp_uses_valid(self):
        """Malformed ts is skipped; if at least one valid ts remains dwell is computed."""
        G = _make_graph()
        _add_node(G, "SRC1")
        _add_node(G, "SRC2")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC1", "MID", amount=10000.0, ts="GARBAGE")
        _add_edge(G, "E2", "SRC2", "MID", amount=10000.0, ts="2024-01-15T10:00:00")
        _add_edge(G, "E3", "MID", "SNK", amount=19000.0, ts="2024-01-15T10:10:00")
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.min_dwell_sec == pytest.approx(600.0)

    def test_only_incoming_transfers_dwell_none(self):
        """No outgoing transfers → cannot compute dwell time."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC", "SNK", amount=10000.0, ts="2024-01-15T10:00:00")
        result = compute_metrics(G)
        snk = next(nm for nm in result.nodes if nm.node_id == "SNK")
        assert snk.min_dwell_sec is None

    def test_timezone_aware_timestamps(self):
        """Timezone-aware timestamps are handled correctly."""
        G = _make_graph()
        _add_node(G, "SRC")
        _add_node(G, "MID")
        _add_node(G, "SNK")
        _add_edge(G, "E1", "SRC", "MID", amount=10000.0, ts="2024-01-15T10:00:00+05:30")
        _add_edge(G, "E2", "MID", "SNK", amount=9000.0, ts="2024-01-15T10:30:00+05:30")
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.min_dwell_sec == pytest.approx(1800.0)


class TestNonTransferEdgesExcluded:
    """Test 17 — OWNS, CALLED etc. don't affect transfer metrics."""

    def test_non_transfer_edges_excluded(self):
        G = _make_graph()
        _add_node(G, "PE_A")
        _add_node(G, "PH_X", "PHONE")
        _add_node(G, "PE_V")
        _add_edge(G, "E1", "PE_A", "PH_X", etype="OWNS")
        _add_edge(G, "E2", "PH_X", "PE_V", etype="CALLED")
        result = compute_metrics(G)
        for nm in result.nodes:
            assert nm.transfer_fan_in == 0
            assert nm.transfer_fan_out == 0
            assert nm.in_amount is None
            assert nm.out_amount is None
            assert nm.pass_through_ratio is None


class TestInOutAmounts:
    """Test 18 — amount sums correct."""

    def test_in_out_amounts(self):
        G = _make_graph()
        _add_node(G, "S1")
        _add_node(G, "S2")
        _add_node(G, "MID")
        _add_node(G, "T1")
        _add_node(G, "T2")
        _add_edge(G, "E1", "S1", "MID", amount=30000.0)
        _add_edge(G, "E2", "S2", "MID", amount=20000.0)
        _add_edge(G, "E3", "MID", "T1", amount=15000.0)
        _add_edge(G, "E4", "MID", "T2", amount=32000.0)
        result = compute_metrics(G)
        mid = next(nm for nm in result.nodes if nm.node_id == "MID")
        assert mid.in_amount == pytest.approx(50000.0)
        assert mid.out_amount == pytest.approx(47000.0)


class TestMetricResultSerialisation:
    """Test 20 — MetricResult JSON round-trip."""

    def test_metric_result_json_round_trip(self):
        G = _make_graph("CASE_SERIAL")
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A", "BA_X", amount=10000.0, ts="2024-01-01T09:00:00")
        result = compute_metrics(G)
        serialised = result.model_dump_json()
        parsed = MetricResult.model_validate_json(serialised)
        assert parsed.case_id == result.case_id
        assert len(parsed.nodes) == len(result.nodes)


# ---------------------------------------------------------------------------
# INTERNAL HELPER TESTS
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_valid_naive_ts(self):
        dt = _parse_ts("2024-01-15T10:00:00")
        assert dt is not None
        assert dt.tzinfo is not None  # should be UTC

    def test_valid_aware_ts(self):
        dt = _parse_ts("2024-01-15T10:00:00+05:30")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_none_input(self):
        assert _parse_ts(None) is None  # type: ignore[arg-type]

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_garbage_string(self):
        assert _parse_ts("NOT_A_DATE") is None


# ---------------------------------------------------------------------------
# COMMUNITIES TESTS
# ---------------------------------------------------------------------------


class TestCommunitiesEmpty:
    """Test 21 — empty graph."""

    def test_empty_graph(self):
        G = _make_graph("CASE_EMPTY")
        result = detect_communities(G)
        assert isinstance(result, CommunityResult)
        assert result.case_id == "CASE_EMPTY"
        assert result.communities == []


class TestCommunitiesOneCluster:
    """Test 22 — all nodes connected → one community."""

    def test_single_community(self):
        G = _make_graph("CASE_ONE")
        for nid in ["PE_A", "BA_X", "BA_Y"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=50000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=45000.0)
        result = detect_communities(G)
        assert len(result.communities) >= 1
        # All nodes should be accounted for
        all_nodes = {n for c in result.communities for n in c.node_ids}
        assert all_nodes == {"PE_A", "BA_X", "BA_Y"}


class TestCommunitiesMultiple:
    """Test 23 — disconnected subgraphs → multiple communities."""

    def test_two_disconnected_components(self):
        G = _make_graph("CASE_SPLIT")
        # Component A
        _add_node(G, "PE_A1")
        _add_node(G, "BA_A2", "BANK_ACCOUNT")
        _add_edge(G, "E1", "PE_A1", "BA_A2", amount=10000.0)
        # Component B — fully isolated from A
        _add_node(G, "PE_B1")
        _add_node(G, "BA_B2", "BANK_ACCOUNT")
        _add_edge(G, "E2", "PE_B1", "BA_B2", amount=20000.0)
        result = detect_communities(G)
        assert len(result.communities) >= 2
        all_nodes = {n for c in result.communities for n in c.node_ids}
        assert all_nodes == {"PE_A1", "BA_A2", "PE_B1", "BA_B2"}


class TestCommunitiesParallelEdges:
    """Test 24 — parallel edges must not duplicate nodes in community."""

    def test_parallel_edges_no_duplicate_nodes(self):
        G = _make_graph("CASE_PARALLEL")
        _add_node(G, "PE_A")
        _add_node(G, "BA_X", "BANK_ACCOUNT")
        # Two parallel edges between same pair
        _add_edge(G, "E1", "PE_A", "BA_X", amount=30000.0)
        _add_edge(G, "E2", "PE_A", "BA_X", amount=20000.0)
        result = detect_communities(G)
        for comm in result.communities:
            # No duplicate node ids within a community
            assert len(comm.node_ids) == len(set(comm.node_ids))
        # Each node appears in exactly one community
        all_nodes = [n for c in result.communities for n in c.node_ids]
        assert len(all_nodes) == len(set(all_nodes))


class TestCommunityNodeIds:
    """Test 25 — community node IDs preserved correctly."""

    def test_node_ids_preserved(self):
        G = _make_graph("CASE_IDS")
        for nid in ["PE_SUSPECT01", "PH_9990000001", "BA_MOCK12345"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_SUSPECT01", "PH_9990000001", etype="OWNS")
        _add_edge(G, "E2", "PE_SUSPECT01", "BA_MOCK12345", etype="OWNS")
        result = detect_communities(G)
        all_ids = {n for c in result.communities for n in c.node_ids}
        assert "PE_SUSPECT01" in all_ids
        assert "PH_9990000001" in all_ids
        assert "BA_MOCK12345" in all_ids


class TestCommunitySizes:
    """Test 26 — community sizes correct."""

    def test_sizes_match_node_id_counts(self):
        G = _make_graph("CASE_SIZE")
        for nid in ["PE_A", "BA_X", "BA_Y", "PE_B"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=10000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=9000.0)
        # PE_B isolated
        result = detect_communities(G)
        for comm in result.communities:
            assert comm.size == len(comm.node_ids)


class TestCommunitiesSortedBySize:
    """Test 27 — communities sorted by size descending."""

    def test_sorted_by_size_descending(self):
        G = _make_graph("CASE_SORTED")
        # Large cluster: 4 nodes
        for nid in ["PE_A", "BA_X", "BA_Y", "BA_Z"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=10000.0)
        _add_edge(G, "E2", "BA_X", "BA_Y", amount=9000.0)
        _add_edge(G, "E3", "BA_Y", "BA_Z", amount=8000.0)
        # Isolated singleton
        _add_node(G, "PE_ISO")
        result = detect_communities(G)
        sizes = [c.size for c in result.communities]
        assert sizes == sorted(sizes, reverse=True)


class TestCommunityResultSerialisation:
    """Test 28 — CommunityResult JSON round-trip."""

    def test_json_round_trip(self):
        G = _make_graph("CASE_SERIAL2")
        for nid in ["PE_A", "BA_X"]:
            _add_node(G, nid)
        _add_edge(G, "E1", "PE_A", "BA_X", amount=10000.0)
        result = detect_communities(G)
        serialised = result.model_dump_json()
        parsed = CommunityResult.model_validate_json(serialised)
        assert parsed.case_id == result.case_id
        assert len(parsed.communities) == len(result.communities)


class TestCommunityMethod:
    """Test 29 — method field is correct string."""

    def test_method_field(self):
        G = _make_graph("CASE_METHOD")
        _add_node(G, "PE_A")
        result = detect_communities(G)
        assert result.method == "greedy_modularity_communities"


# ---------------------------------------------------------------------------
# INTEGRATION — ResolvedGraph → graph_builder → metrics → communities
# ---------------------------------------------------------------------------


class TestIntegration:
    """
    Synthetic end-to-end: ResolvedGraph → build_graph → compute_metrics →
    detect_communities.  Verifies outputs are Pydantic-serialisable and
    compatible with each other.
    """

    # Integration fixture: two victim accounts feed funds into BA_MULE01,
    # which re-forwards them to BA_MULE02 (classic mule pass-through).
    RAW_NODES = [
        {"id": "PE_SUSPECT01", "type": "PERSON", "label": "Suspected Operator 01",
         "attrs": {}, "sources": ["notes.txt#p1"]},
        {"id": "BA_VICTIM01", "type": "BANK_ACCOUNT", "label": "XXXXXX9901",
         "attrs": {"bank": "VictimBank"}, "sources": ["txn.csv#L1"]},
        {"id": "BA_VICTIM02", "type": "BANK_ACCOUNT", "label": "XXXXXX9902",
         "attrs": {"bank": "VictimBank"}, "sources": ["txn.csv#L2"]},
        {"id": "BA_MULE01", "type": "BANK_ACCOUNT", "label": "XXXXXX0001",
         "attrs": {"bank": "MockBank"}, "sources": ["txn.csv#L3"]},
        {"id": "BA_MULE02", "type": "BANK_ACCOUNT", "label": "XXXXXX0002",
         "attrs": {"bank": "MockBank"}, "sources": ["txn.csv#L5"]},
        {"id": "PE_VICTIM01", "type": "PERSON", "label": "Suspected Victim 01",
         "attrs": {}, "sources": ["notes.txt#p2"]},
    ]
    RAW_EDGES = [
        {"id": "E0", "source": "PE_SUSPECT01", "target": "BA_MULE01",
         "type": "OWNS", "attrs": {}, "evidence": "notes.txt#p1"},
        # Victim accounts send funds INTO the mule account
        {"id": "E1", "source": "BA_VICTIM01", "target": "BA_MULE01",
         "type": "TRANSFERRED_TO", "attrs": {"amount": 50000, "ts": "2024-01-15T10:00:00"},
         "evidence": "txn.csv#L1"},
        {"id": "E2", "source": "BA_VICTIM02", "target": "BA_MULE01",
         "type": "TRANSFERRED_TO", "attrs": {"amount": 20000, "ts": "2024-01-15T10:02:00"},
         "evidence": "txn.csv#L2"},
        # Mule forwards funds out to MULE02 (two separate outgoing transfers)
        {"id": "E3", "source": "BA_MULE01", "target": "BA_MULE02",
         "type": "TRANSFERRED_TO", "attrs": {"amount": 45000, "ts": "2024-01-15T10:20:00"},
         "evidence": "txn.csv#L3"},
        {"id": "E4", "source": "BA_MULE01", "target": "BA_MULE02",
         "type": "TRANSFERRED_TO", "attrs": {"amount": 24000, "ts": "2024-01-15T10:25:00"},
         "evidence": "txn.csv#L4"},
    ]

    @pytest.fixture
    def pipeline(self):
        rg = resolve("CASE_INT", self.RAW_NODES, self.RAW_EDGES)
        G = build_graph(rg)
        metrics = compute_metrics(G)
        communities = detect_communities(G)
        return G, metrics, communities

    def test_pipeline_runs_without_error(self, pipeline):
        G, metrics, communities = pipeline
        assert metrics is not None
        assert communities is not None

    def test_metrics_type(self, pipeline):
        _, metrics, _ = pipeline
        assert isinstance(metrics, MetricResult)

    def test_communities_type(self, pipeline):
        _, _, communities = pipeline
        assert isinstance(communities, CommunityResult)

    def test_metrics_serialisable(self, pipeline):
        _, metrics, _ = pipeline
        json_str = metrics.model_dump_json()
        parsed = MetricResult.model_validate_json(json_str)
        assert parsed.case_id == "CASE_INT"

    def test_communities_serialisable(self, pipeline):
        _, _, communities = pipeline
        json_str = communities.model_dump_json()
        parsed = CommunityResult.model_validate_json(json_str)
        assert parsed.case_id == "CASE_INT"

    def test_mule_has_pass_through_near_1(self, pipeline):
        """BA_MULE01: in=50k+20k=70k, out=45k+24k=69k → ratio ≈ 0.9857."""
        _, metrics, _ = pipeline
        mule = next(nm for nm in metrics.nodes if nm.node_id == "BA_MULE01")
        assert mule.in_amount == pytest.approx(70000.0)
        assert mule.out_amount == pytest.approx(69000.0)
        assert mule.pass_through_ratio == pytest.approx(69000.0 / 70000.0)

    def test_parallel_edges_counted_in_fan(self, pipeline):
        """Two outgoing TRANSFERRED_TO edges from MULE01 both counted."""
        _, metrics, _ = pipeline
        mule = next(nm for nm in metrics.nodes if nm.node_id == "BA_MULE01")
        assert mule.transfer_fan_out == 2
        assert mule.transfer_fan_in == 2

    def test_dwell_time_minimum_of_incoming_to_outgoing(self, pipeline):
        """
        BA_MULE01 incoming: E1@10:00, E2@10:02
        BA_MULE01 outgoing: E3@10:20, E4@10:25
        All 4 pairs (in×out): 1200s, 1500s, 1080s, 1380s → minimum = 1080s.
        """
        _, metrics, _ = pipeline
        mule = next(nm for nm in metrics.nodes if nm.node_id == "BA_MULE01")
        assert mule.min_dwell_sec == pytest.approx(1080.0)  # 10:02 → 10:20 = 18min

    def test_community_covers_connected_nodes(self, pipeline):
        _, _, communities = pipeline
        all_nodes = {n for c in communities.communities for n in c.node_ids}
        # All nodes should appear in some community
        assert "PE_SUSPECT01" in all_nodes
        assert "BA_MULE01" in all_nodes
        assert "BA_MULE02" in all_nodes
        assert "BA_VICTIM01" in all_nodes
        assert "BA_VICTIM02" in all_nodes
