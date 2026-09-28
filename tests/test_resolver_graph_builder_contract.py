"""
tests/test_resolver_graph_builder_contract.py

Contract tests: resolver.py output → graph_builder.py input/output.

Covers
------
  1.  Node Pydantic schema (valid, empty-sources, invalid-type, all 7 types)
  2.  Edge Pydantic schema (valid, empty-evidence, invalid-type, all 7 types)
  3.  ResolvedGraph schema (valid, empty)
  4.  resolver.resolve() — output type, node/edge preservation, evidence
      round-trip, invalid-input rejection
  5.  build_graph() — graph type is nx.MultiDiGraph (documented decision),
      case_id, node count, edge count, node attrs, node sources, edge attrs,
      edge evidence, directed semantics, missing-source-node raises,
      missing-target-node raises, empty graph, multiple node types,
      parallel edges between same node pair preserved (key justification
      for MultiDiGraph over DiGraph), edge id preserved as nx edge key

Graph type decision recorded in graph_builder.py module docstring:
  nx.MultiDiGraph is required because nx.DiGraph silently overwrites a
  second edge between the same (source, target) pair, destroying its
  evidence reference — violating rules.md §3.1.

All data is mock/synthetic — no real phone numbers, accounts, or identities.
"""

from __future__ import annotations

import networkx as nx
import pytest
from pydantic import ValidationError

from backend.analysis.graph_builder import build_graph
from backend.schemas.entities import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    ResolvedGraph,
)
from backend.services.resolver import resolve


# ---------------------------------------------------------------------------
# Fixtures — minimal SIM-swap scenario (synthetic / mock data only)
# ---------------------------------------------------------------------------

RAW_NODES = [
    {
        "id": "PE_SUSPECT01",
        "type": "PERSON",
        "label": "Suspected Operator 01",
        "attrs": {"alias": "OP1"},
        "sources": ["raw_notes.txt#p1"],
    },
    {
        "id": "PH_9990000001",
        "type": "PHONE",
        "label": "9990X000001",
        "attrs": {"sim_swapped_on": "2024-01-15"},
        "sources": ["call_logs.csv#L3", "raw_notes.txt#p1"],
    },
    {
        "id": "BA_MOCK12345",
        "type": "BANK_ACCOUNT",
        "label": "XXXXXX12345",
        "attrs": {"bank": "MockBank", "ifsc": "MOCK0001234"},
        "sources": ["transactions.csv#L7"],
    },
    {
        "id": "PE_VICTIM01",
        "type": "PERSON",
        "label": "Suspected Victim 01",
        "attrs": {},
        "sources": ["raw_notes.txt#p2"],
    },
]

RAW_EDGES = [
    {
        "id": "E001",
        "source": "PE_SUSPECT01",
        "target": "PH_9990000001",
        "type": "OWNS",
        "attrs": {},
        "evidence": "raw_notes.txt#p1",
    },
    {
        "id": "E002",
        "source": "PH_9990000001",
        "target": "PE_VICTIM01",
        "type": "CALLED",
        "attrs": {"duration_sec": 42, "ts": "2024-01-15T10:05:00"},
        "evidence": "call_logs.csv#L3",
    },
    {
        "id": "E003",
        "source": "PE_SUSPECT01",
        "target": "BA_MOCK12345",
        "type": "OWNS",
        "attrs": {},
        "evidence": "transactions.csv#L7",
    },
]


# ---------------------------------------------------------------------------
# 1. Pydantic schema — Node validation
# ---------------------------------------------------------------------------


class TestNodeSchema:
    def test_valid_node(self):
        node = Node(
            id="PE_SUSPECT01",
            type=NodeType.PERSON,
            label="Suspected Operator 01",
            attrs={"alias": "OP1"},
            sources=["raw_notes.txt#p1"],
        )
        assert node.id == "PE_SUSPECT01"
        assert node.type == NodeType.PERSON
        assert node.sources == ["raw_notes.txt#p1"]

    def test_node_requires_at_least_one_source(self):
        """rules.md §3.1 — every claim must trace to evidence."""
        with pytest.raises(ValidationError) as exc_info:
            Node(
                id="PE_NOSOURCE",
                type=NodeType.PERSON,
                label="No source node",
                sources=[],
            )
        assert "source" in str(exc_info.value).lower() or "sources" in str(exc_info.value).lower()

    def test_node_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Node(
                id="XX_UNKNOWN",
                type="UNKNOWN_TYPE",  # type: ignore[arg-type]
                label="Bad type",
                sources=["file.txt#L1"],
            )

    def test_all_node_types_accepted(self):
        for nt in NodeType:
            n = Node(id=f"{nt.value}_001", type=nt, label="test", sources=["f.txt#L1"])
            assert n.type == nt


# ---------------------------------------------------------------------------
# 2. Pydantic schema — Edge validation
# ---------------------------------------------------------------------------


class TestEdgeSchema:
    def test_valid_edge(self):
        edge = Edge(
            id="E001",
            source="PE_SUSPECT01",
            target="PH_9990000001",
            type=EdgeType.OWNS,
            attrs={},
            evidence="raw_notes.txt#p1",
        )
        assert edge.id == "E001"
        assert edge.type == EdgeType.OWNS
        assert edge.evidence == "raw_notes.txt#p1"

    def test_edge_requires_evidence(self):
        """rules.md §3.1 — no evidence → edge must not be created."""
        with pytest.raises(ValidationError):
            Edge(
                id="E_BAD",
                source="A",
                target="B",
                type=EdgeType.CALLED,
                evidence="",  # empty — violates min_length=1
            )

    def test_edge_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Edge(
                id="E_BAD2",
                source="A",
                target="B",
                type="NOT_A_TYPE",  # type: ignore[arg-type]
                evidence="file.txt#L1",
            )

    def test_all_edge_types_accepted(self):
        for et in EdgeType:
            e = Edge(
                id=f"E_{et.value}",
                source="A",
                target="B",
                type=et,
                evidence="f.txt#L1",
            )
            assert e.type == et


# ---------------------------------------------------------------------------
# 3. ResolvedGraph schema
# ---------------------------------------------------------------------------


class TestResolvedGraphSchema:
    def test_valid_resolved_graph(self):
        rg = ResolvedGraph(
            case_id="CASE_001",
            nodes=[Node.model_validate(n) for n in RAW_NODES],
            edges=[Edge.model_validate(e) for e in RAW_EDGES],
        )
        assert rg.case_id == "CASE_001"
        assert len(rg.nodes) == 4
        assert len(rg.edges) == 3

    def test_empty_graph_is_valid(self):
        rg = ResolvedGraph(case_id="CASE_EMPTY")
        assert rg.nodes == []
        assert rg.edges == []


# ---------------------------------------------------------------------------
# 4. resolver.resolve() — contract output
# ---------------------------------------------------------------------------


class TestResolver:
    def test_resolve_returns_resolved_graph(self):
        rg = resolve("CASE_001", RAW_NODES, RAW_EDGES)
        assert isinstance(rg, ResolvedGraph)
        assert rg.case_id == "CASE_001"

    def test_resolve_preserves_all_nodes(self):
        rg = resolve("CASE_001", RAW_NODES, RAW_EDGES)
        ids = {n.id for n in rg.nodes}
        assert ids == {"PE_SUSPECT01", "PH_9990000001", "BA_MOCK12345", "PE_VICTIM01"}

    def test_resolve_preserves_all_edges(self):
        rg = resolve("CASE_001", RAW_NODES, RAW_EDGES)
        edge_ids = {e.id for e in rg.edges}
        assert edge_ids == {"E001", "E002", "E003"}

    def test_resolve_preserves_evidence_on_nodes(self):
        rg = resolve("CASE_001", RAW_NODES, RAW_EDGES)
        ph = next(n for n in rg.nodes if n.id == "PH_9990000001")
        assert "call_logs.csv#L3" in ph.sources

    def test_resolve_preserves_evidence_on_edges(self):
        rg = resolve("CASE_001", RAW_NODES, RAW_EDGES)
        e2 = next(e for e in rg.edges if e.id == "E002")
        assert e2.evidence == "call_logs.csv#L3"

    def test_resolve_raises_on_invalid_node(self):
        bad_nodes = [{"id": "X", "type": "PERSON", "label": "Bad", "sources": []}]
        with pytest.raises(ValidationError):
            resolve("CASE_X", bad_nodes, [])


# ---------------------------------------------------------------------------
# 5. build_graph() — contract input and graph structure
# ---------------------------------------------------------------------------


class TestBuildGraph:
    @pytest.fixture
    def resolved(self):
        return resolve("CASE_001", RAW_NODES, RAW_EDGES)

    # ── Graph type ───────────────────────────────────────────────────────────

    def test_graph_type_is_multidigraph(self, resolved):
        """
        Contract requires nx.MultiDiGraph (not nx.DiGraph).

        Reason: nx.DiGraph silently overwrites a second edge between the same
        (source, target) pair, destroying its evidence reference — violating
        rules.md §3.1.  See graph_builder.py module docstring for full
        justification.
        """
        G = build_graph(resolved)
        assert isinstance(G, nx.MultiDiGraph)

    def test_graph_type_is_not_digraph(self, resolved):
        """
        Explicit negative check: result must NOT be the base DiGraph class.
        nx.MultiDiGraph IS a subclass of nx.DiGraph, but is_directed() alone
        is insufficient — we must verify multi-edge support exists.
        """
        G = build_graph(resolved)
        # MultiDiGraph is directed AND supports multiple edges per pair
        assert G.is_directed()
        assert G.is_multigraph()

    # ── Graph-level attributes ───────────────────────────────────────────────

    def test_case_id_preserved(self, resolved):
        G = build_graph(resolved)
        assert G.graph["case_id"] == "CASE_001"

    # ── Node counts and types ────────────────────────────────────────────────

    def test_graph_node_count(self, resolved):
        G = build_graph(resolved)
        assert G.number_of_nodes() == 4

    def test_multiple_node_types(self, resolved):
        """Graph contains nodes of distinct NodeType values."""
        G = build_graph(resolved)
        types_in_graph = {G.nodes[n]["type"] for n in G.nodes}
        assert "PERSON" in types_in_graph
        assert "PHONE" in types_in_graph
        assert "BANK_ACCOUNT" in types_in_graph

    # ── Node attributes ──────────────────────────────────────────────────────

    def test_node_attributes_preserved(self, resolved):
        G = build_graph(resolved)
        attrs = G.nodes["PH_9990000001"]
        assert attrs["type"] == "PHONE"
        assert attrs["label"] == "9990X000001"
        assert attrs["attrs"]["sim_swapped_on"] == "2024-01-15"

    def test_node_source_evidence_preserved(self, resolved):
        """rules.md §3.1 — source evidence must survive the round-trip."""
        G = build_graph(resolved)
        sources = G.nodes["PH_9990000001"]["sources"]
        assert "call_logs.csv#L3" in sources
        assert "raw_notes.txt#p1" in sources

    # ── Edge counts and direction ────────────────────────────────────────────

    def test_graph_edge_count(self, resolved):
        G = build_graph(resolved)
        assert G.number_of_edges() == 3

    def test_directed_transfer_semantics(self, resolved):
        """CALLED edge is directed: phone→victim, NOT victim→phone."""
        G = build_graph(resolved)
        assert G.has_edge("PH_9990000001", "PE_VICTIM01")
        assert not G.has_edge("PE_VICTIM01", "PH_9990000001")

    # ── Edge attributes ──────────────────────────────────────────────────────

    def test_edge_attributes_preserved(self, resolved):
        G = build_graph(resolved)
        edge_data = G.get_edge_data("PH_9990000001", "PE_VICTIM01")
        assert edge_data is not None
        e = edge_data["E002"]
        assert e["type"] == "CALLED"
        assert e["attrs"]["duration_sec"] == 42

    def test_edge_evidence_preserved(self, resolved):
        """rules.md §3.1 — evidence reference must survive the round-trip."""
        G = build_graph(resolved)
        edge_data = G.get_edge_data("PH_9990000001", "PE_VICTIM01")
        e = edge_data["E002"]
        assert e["evidence"] == "call_logs.csv#L3"

    def test_edge_id_preserved_as_key(self, resolved):
        """Edge.id is the MultiDiGraph edge key — enables stable lookup."""
        G = build_graph(resolved)
        # Lookup by the canonical Edge.id used as the nx edge key
        e = G.get_edge_data("PE_SUSPECT01", "PH_9990000001")["E001"]
        assert e["id"] == "E001"
        assert e["type"] == "OWNS"

    # ── Parallel edges (key MultiDiGraph justification) ─────────────────────

    def test_parallel_edges_between_same_pair_preserved(self):
        """
        A node pair may share two independently evidenced edges of different
        types.  nx.DiGraph would silently drop one; nx.MultiDiGraph preserves
        both.  This is the primary reason MultiDiGraph is required.
        """
        nodes = [
            {"id": "PE_A", "type": "PERSON", "label": "Suspected A", "attrs": {}, "sources": ["f.txt#L1"]},
            {"id": "BA_X", "type": "BANK_ACCOUNT", "label": "XXXXXXX", "attrs": {}, "sources": ["t.csv#L1"]},
        ]
        edges = [
            # Same (source, target) pair — two distinct relationship types
            {
                "id": "E_OWN",
                "source": "PE_A",
                "target": "BA_X",
                "type": "OWNS",
                "attrs": {},
                "evidence": "f.txt#L1",
            },
            {
                "id": "E_TRF",
                "source": "PE_A",
                "target": "BA_X",
                "type": "TRANSFERRED_TO",
                "attrs": {"amount": 50000},
                "evidence": "t.csv#L1",
            },
        ]
        rg = resolve("CASE_PARALLEL", nodes, edges)
        G = build_graph(rg)

        # Both edges must be present — not collapsed into one
        assert G.number_of_edges() == 2

        pair_data = G.get_edge_data("PE_A", "BA_X")
        assert pair_data is not None
        assert "E_OWN" in pair_data
        assert "E_TRF" in pair_data

        assert pair_data["E_OWN"]["type"] == "OWNS"
        assert pair_data["E_OWN"]["evidence"] == "f.txt#L1"

        assert pair_data["E_TRF"]["type"] == "TRANSFERRED_TO"
        assert pair_data["E_TRF"]["attrs"]["amount"] == 50000
        assert pair_data["E_TRF"]["evidence"] == "t.csv#L1"

    # ── Integrity errors ─────────────────────────────────────────────────────

    def test_missing_source_node_raises(self, resolved):
        """Edge referencing a node not in the graph must fail explicitly."""
        bad_edge = Edge(
            id="E_BAD",
            source="GHOST_NODE",
            target="PE_VICTIM01",
            type=EdgeType.CALLED,
            evidence="file.txt#L1",
        )
        resolved.edges.append(bad_edge)
        with pytest.raises(ValueError, match="unknown source node"):
            build_graph(resolved)

    def test_missing_target_node_raises(self, resolved):
        """Edge referencing a non-existent target must fail explicitly."""
        bad_edge = Edge(
            id="E_BAD2",
            source="PE_SUSPECT01",
            target="GHOST_TARGET",
            type=EdgeType.TRANSFERRED_TO,
            evidence="file.txt#L1",
        )
        resolved.edges.append(bad_edge)
        with pytest.raises(ValueError, match="unknown target node"):
            build_graph(resolved)

    # ── Empty graph ──────────────────────────────────────────────────────────

    def test_empty_graph_builds_without_error(self):
        rg = ResolvedGraph(case_id="CASE_EMPTY")
        G = build_graph(rg)
        assert isinstance(G, nx.MultiDiGraph)
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0
        assert G.graph["case_id"] == "CASE_EMPTY"
