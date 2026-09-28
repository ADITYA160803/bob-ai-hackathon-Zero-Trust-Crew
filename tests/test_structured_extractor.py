"""
tests/test_structured_extractor.py

Tests for backend/services/structured_extractor.py

Covers:
  1.  extract_transactions — valid CSV
  2.  extract_transactions — empty CSV (header only)
  3.  extract_transactions — rows with missing UPI columns skipped
  4.  extract_call_logs — valid CSV
  5.  extract_call_logs — with location nodes
  6.  extract_call_logs — empty CSV (header only)
  7.  detect_and_extract — transactions.csv detected
  8.  detect_and_extract — call_logs.csv detected
  9.  detect_and_extract — plain text returns None
  10. detect_and_extract — empty string returns None
  11. Evidence references include line numbers
  12. Amount and timestamp stored in edge attrs
  13. LOCATION nodes created from call_logs location column
"""
from __future__ import annotations

import pytest

from backend.schemas.entities import EdgeType, NodeType
from backend.services.structured_extractor import (
    CALL_LOG_HEADERS,
    TRANSACTIONS_HEADERS,
    detect_and_extract,
    extract_call_logs,
    extract_transactions,
)

# ---------------------------------------------------------------------------
# Sample CSV fixtures
# ---------------------------------------------------------------------------

TXN_CSV = """\
timestamp,txn_id,sender_upi,receiver_upi,amount_inr,bank,status
2024-01-15T10:10:00,T001,alice@ybl,bob@sbi,50000,MockHDFC,SUCCESS
2024-01-15T10:22:00,T002,bob@sbi,charlie@pnb,47000,MockSBI,SUCCESS
"""

CALL_CSV = """\
timestamp,caller,receiver,duration_sec,location
2024-01-15T09:55:00,9990000001,9990000002,55,Jamtara
2024-01-15T10:05:00,9990000001,9990000003,40,Jamtara
"""

CALL_CSV_NO_LOCATION = """\
timestamp,caller,receiver,duration_sec
2024-01-15T09:55:00,9990000001,9990000002,55
"""


# ---------------------------------------------------------------------------
# 1. extract_transactions — valid CSV
# ---------------------------------------------------------------------------

class TestExtractTransactions:
    def test_returns_nodes_and_edges(self):
        nodes, edges = extract_transactions(TXN_CSV, "transactions.csv")
        assert len(nodes) > 0
        assert len(edges) > 0

    def test_node_types_are_upi_id(self):
        nodes, _ = extract_transactions(TXN_CSV, "transactions.csv")
        for n in nodes:
            assert n.type == NodeType.UPI_ID

    def test_edge_types_are_transferred_to(self):
        _, edges = extract_transactions(TXN_CSV, "transactions.csv")
        for e in edges:
            assert e.type == EdgeType.TRANSFERRED_TO

    def test_edge_source_target_from_upi_columns(self):
        _, edges = extract_transactions(TXN_CSV, "transactions.csv")
        assert edges[0].source_value == "alice@ybl"
        assert edges[0].target_value == "bob@sbi"

    def test_amount_in_edge_attrs(self):
        _, edges = extract_transactions(TXN_CSV, "transactions.csv")
        assert edges[0].attrs["amount"] == 50000.0

    def test_timestamp_in_edge_attrs(self):
        _, edges = extract_transactions(TXN_CSV, "transactions.csv")
        assert edges[0].attrs["ts"] == "2024-01-15T10:10:00"

    def test_evidence_includes_line_number(self):
        _, edges = extract_transactions(TXN_CSV, "transactions.csv")
        assert "#L" in edges[0].evidence
        assert "transactions.csv" in edges[0].evidence

    def test_two_rows_produce_two_edges(self):
        _, edges = extract_transactions(TXN_CSV, "transactions.csv")
        assert len(edges) == 2

    def test_empty_csv_produces_nothing(self):
        header_only = "timestamp,txn_id,sender_upi,receiver_upi,amount_inr,bank,status\n"
        nodes, edges = extract_transactions(header_only, "transactions.csv")
        assert nodes == []
        assert edges == []

    def test_rows_with_missing_upi_are_skipped(self):
        csv = "timestamp,txn_id,sender_upi,receiver_upi,amount_inr,bank,status\n2024-01-01,,, ,0,X,Y\n"
        nodes, edges = extract_transactions(csv, "transactions.csv")
        assert edges == []


# ---------------------------------------------------------------------------
# 4. extract_call_logs — valid CSV
# ---------------------------------------------------------------------------

class TestExtractCallLogs:
    def test_returns_nodes_and_edges(self):
        nodes, edges = extract_call_logs(CALL_CSV, "call_logs.csv")
        assert len(nodes) > 0
        assert len(edges) > 0

    def test_phone_nodes_created(self):
        nodes, _ = extract_call_logs(CALL_CSV, "call_logs.csv")
        phone_nodes = [n for n in nodes if n.type == NodeType.PHONE]
        assert len(phone_nodes) > 0

    def test_edge_types_are_called(self):
        _, edges = extract_call_logs(CALL_CSV, "call_logs.csv")
        for e in edges:
            assert e.type == EdgeType.CALLED

    def test_duration_in_edge_attrs(self):
        _, edges = extract_call_logs(CALL_CSV, "call_logs.csv")
        assert edges[0].attrs["duration_sec"] == 55.0

    def test_timestamp_in_edge_attrs(self):
        _, edges = extract_call_logs(CALL_CSV, "call_logs.csv")
        assert edges[0].attrs["ts"] == "2024-01-15T09:55:00"

    def test_location_nodes_created(self):
        nodes, _ = extract_call_logs(CALL_CSV, "call_logs.csv")
        loc_nodes = [n for n in nodes if n.type == NodeType.LOCATION]
        assert len(loc_nodes) > 0
        assert any(n.value == "Jamtara" for n in loc_nodes)

    def test_no_location_nodes_when_column_absent(self):
        nodes, _ = extract_call_logs(CALL_CSV_NO_LOCATION, "call_logs.csv")
        loc_nodes = [n for n in nodes if n.type == NodeType.LOCATION]
        assert loc_nodes == []

    def test_evidence_includes_line_number(self):
        _, edges = extract_call_logs(CALL_CSV, "call_logs.csv")
        assert "#L" in edges[0].evidence
        assert "call_logs.csv" in edges[0].evidence

    def test_empty_csv_produces_nothing(self):
        header_only = "timestamp,caller,receiver,duration_sec,location\n"
        nodes, edges = extract_call_logs(header_only, "call_logs.csv")
        assert nodes == []
        assert edges == []


# ---------------------------------------------------------------------------
# 7. detect_and_extract — type detection
# ---------------------------------------------------------------------------

class TestDetectAndExtract:
    def test_detects_transactions_csv(self):
        result = detect_and_extract(TXN_CSV, "transactions.csv")
        assert result is not None
        nodes, edges = result
        assert len(edges) == 2
        assert edges[0].type == EdgeType.TRANSFERRED_TO

    def test_detects_call_logs_csv(self):
        result = detect_and_extract(CALL_CSV, "call_logs.csv")
        assert result is not None
        nodes, edges = result
        assert len(edges) == 2
        assert edges[0].type == EdgeType.CALLED

    def test_plain_text_returns_none(self):
        result = detect_and_extract("This is not a CSV file.", "notes.txt")
        assert result is None

    def test_empty_string_returns_none(self):
        result = detect_and_extract("", "empty.txt")
        assert result is None

    def test_unknown_csv_headers_returns_none(self):
        csv_data = "col1,col2,col3\nv1,v2,v3\n"
        result = detect_and_extract(csv_data, "unknown.csv")
        assert result is None

    def test_transactions_headers_constant(self):
        assert "sender_upi" in TRANSACTIONS_HEADERS
        assert "receiver_upi" in TRANSACTIONS_HEADERS
        assert "amount_inr" in TRANSACTIONS_HEADERS
        assert "txn_id" in TRANSACTIONS_HEADERS

    def test_call_log_headers_constant(self):
        assert "caller" in CALL_LOG_HEADERS
        assert "receiver" in CALL_LOG_HEADERS
        assert "duration_sec" in CALL_LOG_HEADERS
