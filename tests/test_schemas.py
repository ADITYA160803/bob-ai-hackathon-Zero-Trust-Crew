"""
tests/test_schemas.py

Unit tests for backend/schemas/entities.py and backend/schemas/graph.py.

Covers:
  - Valid Node and Edge construction
  - NodeType and EdgeType enumerations (all values accepted)
  - Validation rejects Node with empty sources list
  - Edge attrs carry amount + ts correctly
  - GraphPayload helpers: node_by_id, edges_for_node
  - ExtractionResult defaults (used_fallback=False)
  - Round-trip via model_dump / model_validate (serialisation)
"""
from __future__ import annotations

import os

os.environ.setdefault("JAAL_TESTING", "1")

import pytest
from pydantic import ValidationError

from backend.schemas.entities import Edge, EdgeType, Node, NodeType, RawEdge, RawNode
from backend.schemas.graph import ExtractionResult, GraphPayload


# ---------------------------------------------------------------------------
# Helpers — minimal valid objects
# ---------------------------------------------------------------------------

def _phone_node(node_id: str = "PH_9876500001") -> Node:
    return Node(
        id=node_id,
        type=NodeType.PHONE,
        label="98765 00001",
        attrs={},
        sources=["call_logs.csv#L14"],
    )


def _bank_node(node_id: str = "BA_001122334455") -> Node:
    return Node(
        id=node_id,
        type=NodeType.BANK_ACCOUNT,
        label="XXXXXX4455",
        sources=["transactions.csv#L5"],
    )


def _transfer_edge(edge_id: str = "E101") -> Edge:
    return Edge(
        id=edge_id,
        source="BA_001122334455",
        target="BA_556677889900",
        type=EdgeType.TRANSFERRED_TO,
        attrs={"amount": 45000, "ts": "2023-03-02T11:42:00"},
        evidence="transactions.csv#L22",
    )


# ---------------------------------------------------------------------------
# NodeType enum
# ---------------------------------------------------------------------------

class TestNodeType:
    def test_all_values_accepted(self) -> None:
        expected = {"PERSON", "PHONE", "DEVICE", "BANK_ACCOUNT", "UPI_ID", "IP", "LOCATION"}
        assert {m.value for m in NodeType} == expected

    def test_is_string_enum(self) -> None:
        assert NodeType.PHONE == "PHONE"


# ---------------------------------------------------------------------------
# EdgeType enum
# ---------------------------------------------------------------------------

class TestEdgeType:
    def test_all_values_accepted(self) -> None:
        expected = {
            "OWNS", "USES_DEVICE", "SIM_IN_DEVICE",
            "CALLED", "SMS_SENT", "TRANSFERRED_TO", "LOGGED_IN_FROM",
        }
        assert {m.value for m in EdgeType} == expected

    def test_is_string_enum(self) -> None:
        assert EdgeType.TRANSFERRED_TO == "TRANSFERRED_TO"


# ---------------------------------------------------------------------------
# Node validation
# ---------------------------------------------------------------------------

class TestNode:
    def test_valid_phone_node(self) -> None:
        n = _phone_node()
        assert n.id == "PH_9876500001"
        assert n.type == NodeType.PHONE
        assert n.sources == ["call_logs.csv#L14"]

    def test_valid_device_node_with_imei_attr(self) -> None:
        n = Node(
            id="DEV_123456789012345",
            type=NodeType.DEVICE,
            label="Device 123456789012345",
            attrs={"imei": "123456789012345"},
            sources=["raw_notes.txt#p2"],
        )
        assert n.attrs["imei"] == "123456789012345"

    def test_valid_person_node_with_name_variants(self) -> None:
        n = Node(
            id="PE_RAKESH",
            type=NodeType.PERSON,
            label="Rakesh Kumar",
            attrs={"name_variants": ["Rakesh Kr", "R Kumar"]},
            sources=["raw_notes.txt#p1"],
        )
        assert "Rakesh Kr" in n.attrs["name_variants"]

    def test_empty_sources_raises(self) -> None:
        with pytest.raises(ValidationError):
            Node(
                id="PH_X",
                type=NodeType.PHONE,
                label="X",
                sources=[],
            )

    def test_missing_sources_raises(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="PH_X", type=NodeType.PHONE, label="X")  # type: ignore[call-arg]

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="XX_1", type="UNKNOWN_TYPE", label="x", sources=["f#L1"])  # type: ignore[arg-type]

    def test_attrs_defaults_to_empty_dict(self) -> None:
        n = _bank_node()
        assert n.attrs == {}

    def test_multiple_sources_accepted(self) -> None:
        n = Node(
            id="PH_MULTI",
            type=NodeType.PHONE,
            label="multi",
            sources=["a.csv#L1", "b.txt#p3"],
        )
        assert len(n.sources) == 2

    def test_all_node_types_constructible(self) -> None:
        for nt in NodeType:
            n = Node(id=f"{nt.value}_TEST", type=nt, label="test", sources=["x#L1"])
            assert n.type == nt


# ---------------------------------------------------------------------------
# Edge validation
# ---------------------------------------------------------------------------

class TestEdge:
    def test_valid_transfer_edge(self) -> None:
        e = _transfer_edge()
        assert e.type == EdgeType.TRANSFERRED_TO
        assert e.attrs["amount"] == 45000
        assert e.attrs["ts"] == "2023-03-02T11:42:00"
        assert e.evidence == "transactions.csv#L22"

    def test_edge_without_attrs(self) -> None:
        e = Edge(
            id="E200",
            source="PE_RAKESH",
            target="PH_9876500001",
            type=EdgeType.OWNS,
            evidence="raw_notes.txt#p1",
        )
        assert e.attrs == {}

    def test_called_edge(self) -> None:
        e = Edge(
            id="E300",
            source="PH_9876500001",
            target="PH_9999900000",
            type=EdgeType.CALLED,
            attrs={"duration_s": 42},
            evidence="call_logs.csv#L7",
        )
        assert e.type == EdgeType.CALLED

    def test_invalid_edge_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Edge(
                id="E999",
                source="X",
                target="Y",
                type="FAKE_TYPE",  # type: ignore[arg-type]
                evidence="x#L1",
            )

    def test_all_edge_types_constructible(self) -> None:
        for et in EdgeType:
            e = Edge(
                id=f"E_{et.value}",
                source="A",
                target="B",
                type=et,
                evidence="x#L1",
            )
            assert e.type == et


# ---------------------------------------------------------------------------
# GraphPayload
# ---------------------------------------------------------------------------

class TestGraphPayload:
    def _payload(self) -> GraphPayload:
        n1 = _phone_node("PH_AAA")
        n2 = _bank_node("BA_BBB")
        e1 = Edge(
            id="E1",
            source="PH_AAA",
            target="BA_BBB",
            type=EdgeType.OWNS,
            evidence="x#L1",
        )
        return GraphPayload(nodes=[n1, n2], edges=[e1])

    def test_node_by_id_found(self) -> None:
        gp = self._payload()
        n = gp.node_by_id("PH_AAA")
        assert n is not None
        assert n.type == NodeType.PHONE

    def test_node_by_id_missing_returns_none(self) -> None:
        gp = self._payload()
        assert gp.node_by_id("NONEXISTENT") is None

    def test_edges_for_node(self) -> None:
        gp = self._payload()
        edges = gp.edges_for_node("PH_AAA")
        assert len(edges) == 1
        assert edges[0].id == "E1"

    def test_edges_for_node_as_target(self) -> None:
        gp = self._payload()
        edges = gp.edges_for_node("BA_BBB")
        assert len(edges) == 1

    def test_edges_for_unknown_node(self) -> None:
        gp = self._payload()
        assert gp.edges_for_node("NOBODY") == []

    def test_empty_graph_valid(self) -> None:
        gp = GraphPayload()
        assert gp.nodes == []
        assert gp.edges == []


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------

class TestExtractionResult:
    def test_defaults(self) -> None:
        er = ExtractionResult()
        assert er.nodes == []
        assert er.edges == []
        assert er.used_fallback is False

    def test_used_fallback_flag(self) -> None:
        er = ExtractionResult(used_fallback=True)
        assert er.used_fallback is True

    def test_with_raw_nodes_and_edges(self) -> None:
        n = RawNode(type=NodeType.PHONE, value="9876500001", evidence="x#L1")
        e = RawEdge(
            type=EdgeType.OWNS,
            source_value="Ramesh",
            target_value="9876500001",
            evidence="x#L1",
        )
        er = ExtractionResult(nodes=[n], edges=[e], used_fallback=False)
        assert len(er.nodes) == 1
        assert len(er.edges) == 1


# ---------------------------------------------------------------------------
# Round-trip serialisation
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_node_round_trip(self) -> None:
        n = _phone_node()
        dumped = n.model_dump()
        restored = Node.model_validate(dumped)
        assert restored == n

    def test_edge_round_trip(self) -> None:
        e = _transfer_edge()
        dumped = e.model_dump()
        restored = Edge.model_validate(dumped)
        assert restored == e

    def test_graph_payload_round_trip(self) -> None:
        gp = GraphPayload(nodes=[_phone_node()], edges=[_transfer_edge()])
        dumped = gp.model_dump()
        restored = GraphPayload.model_validate(dumped)
        assert restored.nodes[0].id == gp.nodes[0].id
        assert restored.edges[0].id == gp.edges[0].id

    def test_extraction_result_round_trip(self) -> None:
        n = RawNode(type=NodeType.PHONE, value="9876500001", evidence="x#L1")
        er = ExtractionResult(nodes=[n], used_fallback=True)
        dumped = er.model_dump()
        restored = ExtractionResult.model_validate(dumped)
        assert restored.used_fallback is True
        assert restored.nodes[0].value == "9876500001"
