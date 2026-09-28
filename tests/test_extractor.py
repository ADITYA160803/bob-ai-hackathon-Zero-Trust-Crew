"""
tests/test_extractor.py

Focused tests for backend/services/extractor.py.

Strategy:
  - Bob client is always mocked (no live HTTP).
  - Test the happy path (LLM returns valid JSON).
  - Test the fallback path (BobUnavailableError → regex).
  - Test grounding: ungrounded LLM value is dropped.
  - Test FORCE_FALLBACK flag bypasses Bob.
  - Test UPI regex does not match email addresses.
  - Test evidence line numbers (FIX 1).
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JAAL_TESTING", "1")

import pytest

from backend.schemas.entities import NodeType
from backend.schemas.graph import ExtractionResult
from backend.services.bob_client import BobUnavailableError
from backend.services.extractor import _normalise, extract, _regex_extract
from backend.services.parser import Chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk(text: str, source_ref: str = "notes.txt", start_line: int = 1) -> Chunk:
    lines = text.splitlines()
    end = start_line + max(0, len(lines) - 1)
    return Chunk(text=text, source_ref=source_ref, start_line=start_line, end_line=end)


def _llm_response(nodes: list[dict], edges: list[dict] | None = None) -> dict:
    return {"nodes": nodes, "edges": edges or []}


# ---------------------------------------------------------------------------
# 1. Happy path — Bob returns valid grounded JSON
# ---------------------------------------------------------------------------

class TestExtractHappyPath:
    def test_bob_nodes_returned_in_result(self) -> None:
        chunk = _chunk("Ramesh called 9876500001 on 2024-01-10.", "call_logs.csv")
        response = _llm_response([
            {"type": "PHONE", "value": "9876500001", "attrs": {}, "evidence": "call_logs.csv"},
        ])
        with patch("backend.services.extractor.call_json", return_value=response):
            result = extract([chunk])
        assert not result.used_fallback
        assert any(n.value == "9876500001" for n in result.nodes)

    def test_bob_evidence_has_line_numbers(self) -> None:
        """LLM path: evidence must be source_ref#L<start>-<end> for multi-line chunks."""
        chunk = _chunk("Ramesh called 9876500001.\nSecond line.", "call_logs.csv", start_line=14)
        response = _llm_response([
            {"type": "PHONE", "value": "9876500001", "attrs": {}, "evidence": "call_logs.csv"},
        ])
        with patch("backend.services.extractor.call_json", return_value=response):
            result = extract([chunk])
        node = next(n for n in result.nodes if n.value == "9876500001")
        assert node.evidence == "call_logs.csv#L14-15"

    def test_bob_evidence_single_line(self) -> None:
        """LLM path: single-line chunk → evidence uses #L<n> (no dash)."""
        chunk = _chunk("9876500001 transferred 45000.", "txn.csv", start_line=7)
        response = _llm_response([
            {"type": "PHONE", "value": "9876500001", "attrs": {}, "evidence": "txn.csv"},
        ])
        with patch("backend.services.extractor.call_json", return_value=response):
            result = extract([chunk])
        node = next(n for n in result.nodes if n.value == "9876500001")
        assert node.evidence == "txn.csv#L7"

    def test_bob_edge_returned_in_result(self) -> None:
        chunk = _chunk("9876500001 transferred 45000 to 001122334455.", "txn.csv")
        response = _llm_response(
            nodes=[
                {"type": "PHONE", "value": "9876500001", "attrs": {}, "evidence": "txn.csv"},
                {"type": "BANK_ACCOUNT", "value": "001122334455", "attrs": {}, "evidence": "txn.csv"},
            ],
            edges=[
                {
                    "type": "TRANSFERRED_TO",
                    "source_value": "9876500001",
                    "target_value": "001122334455",
                    "attrs": {"amount": 45000},
                    "evidence": "txn.csv",
                }
            ],
        )
        with patch("backend.services.extractor.call_json", return_value=response):
            result = extract([chunk])
        assert len(result.edges) == 1
        assert result.edges[0].attrs["amount"] == 45000


# ---------------------------------------------------------------------------
# 2. Fallback path — BobUnavailableError triggers regex
# ---------------------------------------------------------------------------

class TestExtractFallback:
    def test_fallback_on_bob_unavailable(self) -> None:
        chunk = _chunk("Call from +919876500001 to 8888800000.", "calls.txt")
        with patch("backend.services.extractor.call_json", side_effect=BobUnavailableError("down")):
            result = extract([chunk])
        assert result.used_fallback is True
        phone_values = {_normalise(n.value) for n in result.nodes if n.type == NodeType.PHONE}
        assert "9876500001" in phone_values or "8888800000" in phone_values

    def test_force_fallback_bypasses_bob(self) -> None:
        chunk = _chunk("IMEI 123456789012345 logged in.", "raw.txt")
        with patch("backend.services.extractor.call_json") as mock_bob:
            with patch.object(__import__("backend.config", fromlist=["settings"]).settings,
                              "FORCE_FALLBACK", True):
                result = extract([chunk])
        mock_bob.assert_not_called()
        assert result.used_fallback is True
        imei_vals = [n.value for n in result.nodes if n.type == NodeType.DEVICE]
        assert "123456789012345" in imei_vals


# ---------------------------------------------------------------------------
# 3. Grounding check — ungrounded LLM value is dropped
# ---------------------------------------------------------------------------

class TestGrounding:
    def test_ungrounded_node_dropped(self) -> None:
        chunk = _chunk("Transfer of 5000 noted.", "notes.txt")
        # LLM invents a phone number not in text
        response = _llm_response([
            {"type": "PHONE", "value": "9999911111", "attrs": {}, "evidence": "notes.txt"},
        ])
        with patch("backend.services.extractor.call_json", return_value=response):
            result = extract([chunk])
        assert all(n.value != "9999911111" for n in result.nodes)


# ---------------------------------------------------------------------------
# 4. Regex fallback — UPI must not match email addresses
# ---------------------------------------------------------------------------

class TestRegexFallback:
    def test_upi_does_not_match_email(self) -> None:
        chunk = _chunk("Email user@example.com and UPI raj@okaxis used.", "notes.txt")
        nodes, _ = _regex_extract(chunk)
        upi_vals = [n.value for n in nodes if n.type == NodeType.UPI_ID]
        assert "user@example.com" not in upi_vals
        assert "raj@okaxis" in upi_vals

    def test_imei_takes_priority_over_phone(self) -> None:
        # 353456789012345 is 15 digits → IMEI, not phone
        chunk = _chunk("Device IMEI 353456789012345 detected.", "notes.txt")
        nodes, _ = _regex_extract(chunk)
        types = {n.type for n in nodes}
        assert NodeType.DEVICE in types
        assert NodeType.PHONE not in types

    def test_regex_evidence_pinned_to_match_line(self) -> None:
        """Regex fallback: each node's evidence is pinned to the exact source line."""
        # Two-line chunk starting at line 14; phone is on line 14, UPI on line 15
        text = "9876500001 called someone.\nUPI raj@okaxis used."
        chunk = _chunk(text, "call_logs.csv", start_line=14)
        nodes, _ = _regex_extract(chunk)
        phone_node = next(n for n in nodes if n.type == NodeType.PHONE)
        upi_node = next(n for n in nodes if n.type == NodeType.UPI_ID)
        assert phone_node.evidence == "call_logs.csv#L14"
        assert upi_node.evidence == "call_logs.csv#L15"
