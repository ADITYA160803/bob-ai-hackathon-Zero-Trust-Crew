"""
tests/test_extract_prompt.py

Tests for:
  - backend/schemas/entities.py  →  RawNode, RawEdge
  - backend/schemas/graph.py     →  ExtractionResult (now holds RawNode/RawEdge)
  - backend/prompts/extract.md   →  {{chunk}} and {{source_ref}} present;
                                    worked-example JSON parses correctly into
                                    RawNode / RawEdge models.

The worked example in extract.md is the single source of truth for the
expected LLM output format, so these tests also act as a contract test:
if the prompt changes its example we catch it here.

No live API calls — we parse the static JSON in the prompt file directly.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("JAAL_TESTING", "1")

import pytest
from pydantic import ValidationError

from backend.schemas.entities import EdgeType, NodeType, RawEdge, RawNode
from backend.schemas.graph import ExtractionResult

# ---------------------------------------------------------------------------
# Locate the prompt and extract the worked-example JSON block
# ---------------------------------------------------------------------------

_PROMPT_PATH = Path(__file__).parent.parent / "backend" / "prompts" / "extract.md"

def _load_prompt_text() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_example_json(prompt_text: str) -> dict:
    """
    Pull the first ```json … ``` block from the prompt and parse it.
    This is the worked example the LLM is shown.
    """
    match = re.search(r"```json\s*(\{.*?\})\s*```", prompt_text, re.DOTALL)
    assert match, "No ```json block found in extract.md"
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# Prompt file sanity checks
# ---------------------------------------------------------------------------

class TestPromptFile:
    def test_prompt_file_exists(self) -> None:
        assert _PROMPT_PATH.exists(), f"Prompt not found: {_PROMPT_PATH}"

    def test_chunk_placeholder_present(self) -> None:
        assert "{{chunk}}" in _load_prompt_text()

    def test_source_ref_placeholder_present(self) -> None:
        assert "{{source_ref}}" in _load_prompt_text()

    def test_all_node_types_documented(self) -> None:
        text = _load_prompt_text()
        for nt in NodeType:
            assert nt.value in text, f"NodeType {nt.value} missing from prompt"

    def test_all_edge_types_documented(self) -> None:
        text = _load_prompt_text()
        for et in EdgeType:
            assert et.value in text, f"EdgeType {et.value} missing from prompt"

    def test_amount_not_a_node_rule_mentioned(self) -> None:
        assert "amount" in _load_prompt_text().lower()

    def test_timestamp_not_a_node_rule_mentioned(self) -> None:
        assert "ISO 8601" in _load_prompt_text()

    def test_example_json_block_exists(self) -> None:
        data = _extract_example_json(_load_prompt_text())
        assert "nodes" in data
        assert "edges" in data


# ---------------------------------------------------------------------------
# Worked-example JSON → RawNode validation
# ---------------------------------------------------------------------------

EXAMPLE_SOURCE_REF = "call_logs.csv#L5"

# Pre-parse the example once at module level to avoid repeated file reads
_EXAMPLE_DATA = _extract_example_json(_load_prompt_text())
_EXAMPLE_NODES = [RawNode.model_validate(n) for n in _EXAMPLE_DATA["nodes"]]
_EXAMPLE_EDGES = [RawEdge.model_validate(e) for e in _EXAMPLE_DATA["edges"]]


class TestWorkedExampleNodes:
    def test_node_count(self) -> None:
        assert len(_EXAMPLE_NODES) == 6

    def test_person_node_present(self) -> None:
        persons = [n for n in _EXAMPLE_NODES if n.type == NodeType.PERSON]
        assert len(persons) == 1
        assert persons[0].value == "Ramesh Kumar"
        assert persons[0].evidence == EXAMPLE_SOURCE_REF

    def test_phone_node_present(self) -> None:
        phones = [n for n in _EXAMPLE_NODES if n.type == NodeType.PHONE]
        assert len(phones) == 1
        assert phones[0].value == "9876500001"

    def test_bank_account_node_present(self) -> None:
        accounts = [n for n in _EXAMPLE_NODES if n.type == NodeType.BANK_ACCOUNT]
        assert len(accounts) == 1
        assert accounts[0].value == "001122334455"

    def test_upi_node_present(self) -> None:
        upis = [n for n in _EXAMPLE_NODES if n.type == NodeType.UPI_ID]
        assert len(upis) == 1
        assert upis[0].value == "ramesh@okaxis"

    def test_device_node_has_imei_attr(self) -> None:
        devices = [n for n in _EXAMPLE_NODES if n.type == NodeType.DEVICE]
        assert len(devices) == 1
        assert devices[0].value == "353456789012345"
        assert devices[0].attrs.get("imei") == "353456789012345"

    def test_ip_node_present(self) -> None:
        ips = [n for n in _EXAMPLE_NODES if n.type == NodeType.IP]
        assert len(ips) == 1
        assert ips[0].value == "203.0.113.42"

    def test_no_amount_node(self) -> None:
        """Amount must NOT be a node — it goes in edge attrs."""
        values = [n.value for n in _EXAMPLE_NODES]
        assert "45000" not in values
        assert "45,000" not in values

    def test_no_timestamp_node(self) -> None:
        """Timestamp must NOT be a node — it goes in edge attrs."""
        values = [n.value for n in _EXAMPLE_NODES]
        assert not any("2023-03-02" in v for v in values)

    def test_all_nodes_have_evidence(self) -> None:
        for n in _EXAMPLE_NODES:
            assert n.evidence, f"Node {n.value} missing evidence"
            assert EXAMPLE_SOURCE_REF in n.evidence


# ---------------------------------------------------------------------------
# Worked-example JSON → RawEdge validation
# ---------------------------------------------------------------------------

class TestWorkedExampleEdges:
    def test_edge_count(self) -> None:
        assert len(_EXAMPLE_EDGES) == 4

    def test_owns_edge(self) -> None:
        owns = [e for e in _EXAMPLE_EDGES if e.type == EdgeType.OWNS]
        assert len(owns) == 1
        assert owns[0].source_value == "Ramesh Kumar"
        assert owns[0].target_value == "9876500001"

    def test_transferred_to_edge_with_amount_and_ts(self) -> None:
        transfers = [e for e in _EXAMPLE_EDGES if e.type == EdgeType.TRANSFERRED_TO]
        assert len(transfers) == 1
        t = transfers[0]
        assert t.source_value == "9876500001"
        assert t.target_value == "001122334455"
        assert t.attrs.get("amount") == 45000
        assert t.attrs.get("ts") == "2023-03-02T11:42:00"

    def test_uses_device_edge(self) -> None:
        uses = [e for e in _EXAMPLE_EDGES if e.type == EdgeType.USES_DEVICE]
        assert len(uses) == 1
        assert uses[0].source_value == "Ramesh Kumar"
        assert uses[0].target_value == "353456789012345"

    def test_logged_in_from_edge(self) -> None:
        logins = [e for e in _EXAMPLE_EDGES if e.type == EdgeType.LOGGED_IN_FROM]
        assert len(logins) == 1
        assert logins[0].source_value == "Ramesh Kumar"
        assert logins[0].target_value == "203.0.113.42"

    def test_all_edges_have_evidence(self) -> None:
        for e in _EXAMPLE_EDGES:
            assert e.evidence, f"Edge {e.type} missing evidence"
            assert EXAMPLE_SOURCE_REF in e.evidence


# ---------------------------------------------------------------------------
# RawNode model validation
# ---------------------------------------------------------------------------

class TestRawNode:
    def test_valid_phone_raw_node(self) -> None:
        n = RawNode(type=NodeType.PHONE, value="9876500001", evidence="x#L1")
        assert n.value == "9876500001"
        assert n.attrs == {}

    def test_device_without_imei_raises(self) -> None:
        with pytest.raises(ValidationError, match="imei"):
            RawNode(type=NodeType.DEVICE, value="123456789012345", evidence="x#L1")

    def test_device_with_imei_ok(self) -> None:
        n = RawNode(
            type=NodeType.DEVICE,
            value="123456789012345",
            attrs={"imei": "123456789012345"},
            evidence="x#L1",
        )
        assert n.attrs["imei"] == "123456789012345"

    def test_missing_evidence_raises(self) -> None:
        with pytest.raises(ValidationError):
            RawNode(type=NodeType.PHONE, value="9876500001")  # type: ignore[call-arg]

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            RawNode(type="GADGET", value="x", evidence="x#L1")  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        n = RawNode(type=NodeType.UPI_ID, value="raj@upi", evidence="f#L3")
        assert RawNode.model_validate(n.model_dump()) == n


# ---------------------------------------------------------------------------
# RawEdge model validation
# ---------------------------------------------------------------------------

class TestRawEdge:
    def test_valid_raw_edge(self) -> None:
        e = RawEdge(
            type=EdgeType.CALLED,
            source_value="9876500001",
            target_value="9999900000",
            evidence="call_logs.csv#L7",
        )
        assert e.attrs == {}

    def test_transfer_edge_with_attrs(self) -> None:
        e = RawEdge(
            type=EdgeType.TRANSFERRED_TO,
            source_value="9876500001",
            target_value="001122334455",
            attrs={"amount": 45000, "ts": "2023-03-02T11:42:00"},
            evidence="txn.csv#L22",
        )
        assert e.attrs["amount"] == 45000
        assert e.attrs["ts"] == "2023-03-02T11:42:00"

    def test_invalid_edge_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            RawEdge(
                type="FAKE",  # type: ignore[arg-type]
                source_value="A",
                target_value="B",
                evidence="x#L1",
            )

    def test_missing_evidence_raises(self) -> None:
        with pytest.raises(ValidationError):
            RawEdge(type=EdgeType.OWNS, source_value="A", target_value="B")  # type: ignore[call-arg]

    def test_round_trip(self) -> None:
        e = RawEdge(
            type=EdgeType.OWNS,
            source_value="Ramesh Kumar",
            target_value="9876500001",
            evidence="notes.txt#p1",
        )
        assert RawEdge.model_validate(e.model_dump()) == e


# ---------------------------------------------------------------------------
# ExtractionResult with RawNode / RawEdge
# ---------------------------------------------------------------------------

class TestExtractionResultRaw:
    def test_holds_raw_nodes_and_edges(self) -> None:
        n = RawNode(type=NodeType.PHONE, value="9876500001", evidence="x#L1")
        e = RawEdge(
            type=EdgeType.OWNS,
            source_value="Ramesh",
            target_value="9876500001",
            evidence="x#L1",
        )
        er = ExtractionResult(nodes=[n], edges=[e])
        assert er.nodes[0].value == "9876500001"
        assert er.edges[0].source_value == "Ramesh"
        assert er.used_fallback is False

    def test_used_fallback_flag(self) -> None:
        er = ExtractionResult(used_fallback=True)
        assert er.used_fallback is True

    def test_round_trip(self) -> None:
        n = RawNode(type=NodeType.IP, value="10.0.0.1", evidence="log#L2")
        er = ExtractionResult(nodes=[n], used_fallback=False)
        restored = ExtractionResult.model_validate(er.model_dump())
        assert restored.nodes[0].value == "10.0.0.1"
