"""
backend/services/structured_extractor.py

Structured CSV extractor — deterministic, no LLM needed.
Handles transactions.csv and call_logs.csv by known headers.
"""
from __future__ import annotations

import csv
import io

from backend.schemas.entities import EdgeType, NodeType, RawEdge, RawNode


def extract_transactions(
    content: str, source_ref: str
) -> tuple[list[RawNode], list[RawEdge]]:
    """transactions.csv: timestamp,txn_id,sender_upi,receiver_upi,amount_inr,bank,status"""
    nodes: list[RawNode] = []
    edges: list[RawEdge] = []
    reader = csv.DictReader(io.StringIO(content))
    for row_num, row in enumerate(reader, start=2):  # 1-indexed, row 1 = header
        src = row.get("sender_upi", "").strip()
        tgt = row.get("receiver_upi", "").strip()
        if not src or not tgt:
            continue
        ref = f"{source_ref}#L{row_num}"
        nodes.append(RawNode(type=NodeType.UPI_ID, value=src, evidence=ref))
        nodes.append(RawNode(type=NodeType.UPI_ID, value=tgt, evidence=ref))
        attrs: dict = {}
        try:
            attrs["amount"] = float(row.get("amount_inr", "") or 0)
        except ValueError:
            pass
        ts = row.get("timestamp", "").strip()
        if ts:
            attrs["ts"] = ts
        edges.append(
            RawEdge(
                type=EdgeType.TRANSFERRED_TO,
                source_value=src,
                target_value=tgt,
                attrs=attrs,
                evidence=ref,
            )
        )
    return nodes, edges


def extract_call_logs(
    content: str, source_ref: str
) -> tuple[list[RawNode], list[RawEdge]]:
    """call_logs.csv: timestamp,caller,receiver,duration_sec,location"""
    nodes: list[RawNode] = []
    edges: list[RawEdge] = []
    reader = csv.DictReader(io.StringIO(content))
    for row_num, row in enumerate(reader, start=2):
        caller = row.get("caller", "").strip()
        receiver = row.get("receiver", "").strip()
        if not caller or not receiver:
            continue
        ref = f"{source_ref}#L{row_num}"
        nodes.append(RawNode(type=NodeType.PHONE, value=caller, evidence=ref))
        nodes.append(RawNode(type=NodeType.PHONE, value=receiver, evidence=ref))
        attrs: dict = {}
        try:
            attrs["duration_sec"] = float(row.get("duration_sec", "") or 0)
        except ValueError:
            pass
        ts = row.get("timestamp", "").strip()
        if ts:
            attrs["ts"] = ts
        edges.append(
            RawEdge(
                type=EdgeType.CALLED,
                source_value=caller,
                target_value=receiver,
                attrs=attrs,
                evidence=ref,
            )
        )
        loc = row.get("location", "").strip()
        if loc:
            nodes.append(RawNode(type=NodeType.LOCATION, value=loc, evidence=ref))
    return nodes, edges


TRANSACTIONS_HEADERS = {"txn_id", "sender_upi", "receiver_upi", "amount_inr"}
CALL_LOG_HEADERS = {"caller", "receiver", "duration_sec"}


def detect_and_extract(
    content: str, source_ref: str
) -> tuple[list[RawNode], list[RawEdge]] | None:
    """
    Detect CSV type from headers and extract.

    Returns (nodes, edges) tuple if the content matches a known CSV schema,
    or None if the content is not a recognised CSV type.
    """
    try:
        reader = csv.DictReader(io.StringIO(content))
        headers = set(reader.fieldnames or [])
        if TRANSACTIONS_HEADERS.issubset(headers):
            return extract_transactions(content, source_ref)
        if CALL_LOG_HEADERS.issubset(headers):
            return extract_call_logs(content, source_ref)
    except Exception:
        pass
    return None
