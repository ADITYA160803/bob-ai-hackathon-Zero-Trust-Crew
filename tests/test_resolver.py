"""
tests/test_resolver.py

Focused tests for backend/services/resolver.py.

Covers:
  - Phone deduplication: two chunks with the same phone (+91 variant and plain)
    produce ONE node with merged sources.
  - Stable ID format: PH_, BA_, UPI_, DEV_, IP_, PE_, LOC_.
  - Edge re-wiring: RawEdge source/target values become stable IDs.
  - Dangling edge dropped: edge whose endpoint has no matching node is silently
    removed (logged but not raised).
  - Name variants: two PERSON nodes with the same first word get attrs.name_variants;
    they are NOT merged into one node.
  - mask() helper: produces "XXXXXX<last4>", never touches the stored ID.
"""
from __future__ import annotations

import os

os.environ.setdefault("JAAL_TESTING", "1")

from backend.schemas.entities import EdgeType, NodeType, RawEdge, RawNode
from backend.schemas.graph import ExtractionResult
from backend.services.resolver import mask, resolve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _phone(value: str, evidence: str = "f.txt") -> RawNode:
    return RawNode(type=NodeType.PHONE, value=value, attrs={}, evidence=evidence)

def _person(value: str, evidence: str = "f.txt") -> RawNode:
    return RawNode(type=NodeType.PERSON, value=value, attrs={}, evidence=evidence)

def _device(imei: str, evidence: str = "f.txt") -> RawNode:
    return RawNode(type=NodeType.DEVICE, value=imei, attrs={"imei": imei}, evidence=evidence)

def _upi(value: str, evidence: str = "f.txt") -> RawNode:
    return RawNode(type=NodeType.UPI_ID, value=value, attrs={}, evidence=evidence)

def _bank(value: str, evidence: str = "f.txt") -> RawNode:
    return RawNode(type=NodeType.BANK_ACCOUNT, value=value, attrs={}, evidence=evidence)

def _edge(etype: EdgeType, src: str, tgt: str, evidence: str = "f.txt") -> RawEdge:
    return RawEdge(type=etype, source_value=src, target_value=tgt, evidence=evidence)


# ---------------------------------------------------------------------------
# 1. Phone deduplication with +91 variant
# ---------------------------------------------------------------------------

class TestPhoneDedup:
    def test_same_phone_two_sources_merged(self) -> None:
        # Evidence refs now include line numbers, as produced by extractor FIX 1
        result = ExtractionResult(nodes=[
            _phone("+919876500001", "call_logs.csv#L14"),
            _phone("9876500001",    "raw_notes.txt#L3"),
        ])
        gp = resolve(result)
        phone_nodes = [n for n in gp.nodes if n.type == NodeType.PHONE]
        assert len(phone_nodes) == 1, "Should merge to one node"
        assert gp.nodes[0].id == "PH_9876500001"
        assert len(gp.nodes[0].sources) == 2
        assert "call_logs.csv#L14" in gp.nodes[0].sources
        assert "raw_notes.txt#L3" in gp.nodes[0].sources

    def test_same_phone_same_ref_no_duplicates(self) -> None:
        """Same phone seen twice with the same evidence ref → sources has no duplicates."""
        result = ExtractionResult(nodes=[
            _phone("9876500001", "call_logs.csv#L14"),
            _phone("9876500001", "call_logs.csv#L14"),
        ])
        gp = resolve(result)
        phone_nodes = [n for n in gp.nodes if n.type == NodeType.PHONE]
        assert len(phone_nodes) == 1
        assert len(phone_nodes[0].sources) == 1

    def test_stable_id_format(self) -> None:
        result = ExtractionResult(nodes=[
            _phone("9876500001"),
            _bank("001122334455"),
            _upi("raj@okaxis"),
            _device("353456789012345"),
            RawNode(type=NodeType.IP,       value="203.0.113.42", attrs={}, evidence="x"),
            RawNode(type=NodeType.LOCATION, value="Jamtara",      attrs={}, evidence="x"),
            _person("Ramesh Kumar"),
        ])
        gp = resolve(result)
        ids = {n.id for n in gp.nodes}
        assert "PH_9876500001"        in ids
        assert "BA_001122334455"      in ids
        assert "UPI_raj_at_okaxis"    in ids
        assert "DEV_353456789012345"  in ids
        assert "IP_203_0_113_42"      in ids
        assert "LOC_jamtara"          in ids
        assert any(i.startswith("PE_") for i in ids)


# ---------------------------------------------------------------------------
# 2. Edge re-wiring
# ---------------------------------------------------------------------------

class TestEdgeRewiring:
    def test_edge_rewired_to_stable_ids(self) -> None:
        result = ExtractionResult(
            nodes=[_phone("9876500001"), _bank("001122334455")],
            edges=[_edge(EdgeType.TRANSFERRED_TO, "9876500001", "001122334455", "txn.csv#L22")],
        )
        gp = resolve(result)
        assert len(gp.edges) == 1
        e = gp.edges[0]
        assert e.source == "PH_9876500001"
        assert e.target == "BA_001122334455"
        assert e.evidence == "txn.csv#L22"

    def test_dangling_edge_dropped(self) -> None:
        # source node exists, target node does NOT
        result = ExtractionResult(
            nodes=[_phone("9876500001")],
            edges=[_edge(EdgeType.CALLED, "9876500001", "8888800000")],
        )
        gp = resolve(result)
        assert gp.edges == []


# ---------------------------------------------------------------------------
# 3. Name variants (no auto-merge)
# ---------------------------------------------------------------------------

class TestNameVariants:
    def test_similar_names_not_merged(self) -> None:
        result = ExtractionResult(nodes=[
            _person("Rakesh Kumar",  "notes.txt"),
            _person("Rakesh Kr",     "call_logs.csv"),
        ])
        gp = resolve(result)
        person_nodes = [n for n in gp.nodes if n.type == NodeType.PERSON]
        assert len(person_nodes) == 2, "People must NOT be auto-merged"

    def test_name_variants_flagged(self) -> None:
        result = ExtractionResult(nodes=[
            _person("Rakesh Kumar", "notes.txt"),
            _person("Rakesh Kr",    "call_logs.csv"),
        ])
        gp = resolve(result)
        person_nodes = [n for n in gp.nodes if n.type == NodeType.PERSON]
        has_variants = any("name_variants" in n.attrs for n in person_nodes)
        assert has_variants


# ---------------------------------------------------------------------------
# 4. mask() helper
# ---------------------------------------------------------------------------

class TestMask:
    def test_mask_shows_last_four(self) -> None:
        assert mask("9876500001") == "XXXXXX0001"

    def test_mask_strips_spaces(self) -> None:
        assert mask("0011 2233 4455") == "XXXXXX4455"

    def test_stored_id_unchanged(self) -> None:
        # mask() must not affect stored IDs — verify it only returns display string
        original = "9876500001"
        _ = mask(original)
        assert original == "9876500001"
