"""
backend/schemas/graph.py

Pydantic models for the full graph payload returned by
GET /api/cases/{id}/graph and used internally between pipeline stages.

GraphPayload     — post-resolution graph (nodes + edges), sent to frontend.
ExtractionResult — raw LLM/regex output (RawNode + RawEdge) before resolution;
                   carries used_fallback flag.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from backend.schemas.entities import Edge, Node, RawEdge, RawNode


# ---------------------------------------------------------------------------
# Graph payload (post-resolution, ready for the frontend)
# ---------------------------------------------------------------------------

class GraphPayload(BaseModel):
    """
    Nodes + edges for one case, ready to be serialised and sent to the
    frontend or stored as JSON.

    Matches the shape consumed by GET /api/cases/{id}/graph.
    """

    nodes: List[Node] = Field(default_factory=list)
    edges: List[Edge] = Field(default_factory=list)

    # Convenience helpers -------------------------------------------------

    def node_by_id(self, node_id: str) -> Node | None:
        """Return the node with the given ID, or None."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def edges_for_node(self, node_id: str) -> List[Edge]:
        """Return all edges where the node is source or target."""
        return [
            e for e in self.edges
            if e.source == node_id or e.target == node_id
        ]

    def to_resolved(self, case_id: str) -> "ResolvedGraph":
        """Convert this GraphPayload to a ResolvedGraph for the analysis pipeline."""
        from backend.schemas.entities import ResolvedGraph
        return ResolvedGraph(case_id=case_id, nodes=self.nodes, edges=self.edges)


# ---------------------------------------------------------------------------
# Extraction result (pre-resolution, extractor → resolver boundary)
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    """
    Raw extraction output before entity resolution.

    Holds RawNode / RawEdge items exactly as returned by the LLM or regex
    fallback.  The resolver normalises values, merges duplicates, assigns
    stable IDs, and produces a GraphPayload.
    """

    nodes: List[RawNode] = Field(default_factory=list)
    edges: List[RawEdge] = Field(default_factory=list)
    used_fallback: bool = Field(
        default=False,
        description=(
            "True when the regex fallback was used instead of (or in "
            "addition to) the Bob LLM extractor."
        ),
    )
