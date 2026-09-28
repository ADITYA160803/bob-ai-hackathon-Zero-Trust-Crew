"""
backend/schemas/entities.py

Pydantic models for nodes and edges, matching architecture.md § 2.5 exactly.

Two layers:

RAW  (extractor → resolver boundary)
─────────────────────────────────────
RawNode  {type, value, attrs, evidence}
RawEdge  {type, source_value, target_value, attrs, evidence}
  — value is the identifier exactly as written in the source text.
  — The resolver assigns stable IDs and produces Node/Edge below.

RESOLVED  (resolver → frontend / graph builder)
────────────────────────────────────────────────
Node  {id, type, label, attrs, sources}   — matches architecture.md § 2.5
Edge  {id, source, target, type, attrs, evidence}
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    PERSON       = "PERSON"
    PHONE        = "PHONE"
    DEVICE       = "DEVICE"        # IMEI lives in attrs["imei"]
    BANK_ACCOUNT = "BANK_ACCOUNT"
    UPI_ID       = "UPI_ID"
    IP           = "IP"
    LOCATION     = "LOCATION"


class EdgeType(str, Enum):
    OWNS            = "OWNS"
    USES_DEVICE     = "USES_DEVICE"
    SIM_IN_DEVICE   = "SIM_IN_DEVICE"
    CALLED          = "CALLED"
    SMS_SENT        = "SMS_SENT"
    TRANSFERRED_TO  = "TRANSFERRED_TO"
    LOGGED_IN_FROM  = "LOGGED_IN_FROM"


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class Node(BaseModel):
    """A single entity node in the fraud network graph."""

    id: str = Field(
        ...,
        description="Stable resolver-assigned ID, e.g. PH_9876500001.",
    )
    type: NodeType = Field(..., description="Entity category.")
    label: str = Field(..., description="Human-readable display string.")
    attrs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional attributes. Common keys: imei (DEVICE), "
            "sim_swapped_on (PHONE), name_variants (PERSON)."
        ),
    )
    sources: List[str] = Field(
        ...,
        min_length=1,
        description="Evidence references, e.g. ['call_logs.csv#L14']. "
                    "Must have at least one entry.",
    )

    @field_validator("sources")
    @classmethod
    def _sources_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("A node must have at least one source reference.")
        return v


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

class Edge(BaseModel):
    """A directed relationship between two nodes."""

    id: str = Field(..., description="Stable edge ID, e.g. E101.")
    source: str = Field(..., description="Source node ID.")
    target: str = Field(..., description="Target node ID.")
    type: EdgeType = Field(..., description="Relationship type.")
    attrs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional attributes. Common keys: amount (INR int), "
            "ts (ISO-8601 string)."
        ),
    )
    evidence: str = Field(
        ...,
        min_length=1,
        description="Single evidence reference, e.g. 'transactions.csv#L22'.",
    )


# ---------------------------------------------------------------------------
# RawNode  — extractor output before resolver assigns stable IDs
# ---------------------------------------------------------------------------

class RawNode(BaseModel):
    """
    A node as returned directly by the LLM extractor or regex fallback.

    ``value`` holds the identifier exactly as it appears in the source text.
    The resolver normalises and deduplicates these before producing Node objects
    with stable IDs.

    DEVICE nodes must carry ``attrs["imei"]`` equal to ``value``.
    """

    type: NodeType = Field(..., description="Entity category.")
    value: str = Field(
        ...,
        description="Raw identifier as written in the source text.",
    )
    attrs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional attributes. DEVICE nodes must include attrs['imei']. "
            "Amount and Timestamp must NOT appear as nodes — they belong in "
            "edge attrs."
        ),
    )
    evidence: str = Field(
        ...,
        description="Evidence reference, e.g. 'call_logs.csv#L5'.",
    )

    @model_validator(mode="after")
    def _device_requires_imei(self) -> "RawNode":
        if self.type == NodeType.DEVICE and "imei" not in self.attrs:
            raise ValueError("DEVICE node must include attrs['imei'].")
        return self


# ---------------------------------------------------------------------------
# RawEdge  — extractor output before resolver assigns stable IDs
# ---------------------------------------------------------------------------

class RawEdge(BaseModel):
    """
    A directed relationship as returned directly by the LLM extractor.

    ``source_value`` and ``target_value`` correspond to the ``value`` fields of
    the two endpoint RawNodes.  The resolver rewires them to stable node IDs.

    Amounts (INR number) and timestamps (ISO 8601) go in ``attrs``, never as
    separate nodes.
    """

    type: EdgeType = Field(..., description="Relationship type.")
    source_value: str = Field(
        ...,
        description="Raw value of the source node (as written in source text).",
    )
    target_value: str = Field(
        ...,
        description="Raw value of the target node (as written in source text).",
    )
    attrs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional. 'amount' (INR number) and/or 'ts' (ISO-8601 string) "
            "for TRANSFERRED_TO edges."
        ),
    )
    evidence: str = Field(
        ...,
        description="Evidence reference, e.g. 'transactions.csv#L22'.",
    )


# ---------------------------------------------------------------------------
# ResolvedGraph  — resolver output used by the analysis pipeline
# ---------------------------------------------------------------------------

class ResolvedGraph(BaseModel):
    """
    Post-resolution entity graph, ready for the analysis pipeline.

    Produced by resolver.resolve(case_id, raw_nodes, raw_edges) or by
    GraphPayload.to_resolved(case_id).  Consumed by
    backend/analysis/graph_builder.build_graph().
    """

    case_id: str = Field(..., min_length=1)
    nodes: List[Node] = Field(default_factory=list)
    edges: List[Edge] = Field(default_factory=list)
