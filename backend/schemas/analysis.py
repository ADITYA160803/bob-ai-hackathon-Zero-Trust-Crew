"""
backend/schemas/analysis.py

Pydantic output models for the analytics layer.

All objects produced by:
  - backend/analysis/metrics.py
  - backend/analysis/communities.py
  - backend/analysis/hierarchy.py
  - backend/analysis/pattern_classifier.py  (future)

…must cross module boundaries as one of these types.

Do NOT duplicate Node, Edge, or ResolvedGraph from entities.py.

Design rules
------------
* Every model must be JSON-serialisable (FastAPI / Pydantic .model_dump()).
* Optional fields use None not absent keys so serialisation is stable.
* No field carries invented data — if a metric cannot be computed the field
  is None or an empty collection with a documented reason.
* Models are intentionally flat; complex nesting only where the architecture
  AnalysisResult schema (§2.5) requires it.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Metrics output models
# ---------------------------------------------------------------------------


class NodeMetrics(BaseModel):
    """
    All computed metrics for a single node in the fraud graph.

    Fields
    ------
    node_id          : str   – matches Node.id
    degree_centrality: float – normalised in+out degree (NetworkX convention)
    in_degree        : int   – raw count of incoming edges (all types)
    out_degree       : int   – raw count of outgoing edges (all types)
    betweenness      : float – normalised betweenness centrality
    transfer_fan_in  : int   – count of incoming TRANSFERRED_TO edges
    transfer_fan_out : int   – count of outgoing TRANSFERRED_TO edges
    in_amount        : Optional[float]  – sum of incoming transfer amounts (INR)
                        None when no TRANSFERRED_TO amounts are present
    out_amount       : Optional[float]  – sum of outgoing transfer amounts (INR)
                        None when no TRANSFERRED_TO amounts are present
    pass_through_ratio: Optional[float] – see metrics.py for exact definition
                        None when denominator is zero (no incoming transfers)
    min_dwell_sec    : Optional[float]  – shortest gap between any incoming
                        and any outgoing TRANSFERRED_TO edge timestamp (seconds)
                        None when insufficient timestamp data
    """

    node_id: str
    degree_centrality: float = Field(
        ...,
        ge=0.0,
        description=(
            "Normalised degree centrality from nx.degree_centrality(). "
            "On a MultiDiGraph this CAN exceed 1.0 when a node has multiple "
            "parallel edges to the same neighbour, because NetworkX counts "
            "each parallel edge independently in the degree while dividing "
            "by (n-1). This is correct MultiDiGraph behaviour and intentional."
        ),
    )
    in_degree: int = Field(..., ge=0)
    out_degree: int = Field(..., ge=0)
    betweenness: float = Field(..., ge=0.0)
    transfer_fan_in: int = Field(..., ge=0)
    transfer_fan_out: int = Field(..., ge=0)
    in_amount: Optional[float] = None
    out_amount: Optional[float] = None
    pass_through_ratio: Optional[float] = None
    min_dwell_sec: Optional[float] = None


class MetricResult(BaseModel):
    """
    Complete metrics result for a case graph.

    case_id : str              – matches ResolvedGraph.case_id
    nodes   : list[NodeMetrics] – one entry per node in the graph
    """

    case_id: str
    nodes: list[NodeMetrics] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Community output models
# ---------------------------------------------------------------------------


class Community(BaseModel):
    """
    A single detected community (graph cluster).

    A community is a structural finding — a set of nodes that are more
    densely connected to each other than to the rest of the graph.
    It does NOT imply guilt or organisational role.

    community_id : int     – 0-based index assigned by detection order
    node_ids     : list[str] – canonical node ids in this community
    size         : int     – len(node_ids) for convenience
    """

    community_id: int = Field(..., ge=0)
    node_ids: list[str]
    size: int = Field(..., ge=1)


class CommunityResult(BaseModel):
    """
    Complete community detection result for a case graph.

    case_id     : str             – matches ResolvedGraph.case_id
    communities : list[Community] – detected communities, sorted by size desc
    method      : str             – algorithm used (for audit trail)
    """

    case_id: str
    communities: list[Community] = Field(default_factory=list)
    method: str = "greedy_modularity_communities"


# ---------------------------------------------------------------------------
# Hierarchy / Role scoring output models
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """
    Fraud network role assignments (architecture.md §2.6).

    These are risk indicators only — NOT conclusions of guilt.
    Always qualify with "suspected", "possible", or "indicator of" in
    any human-readable output.
    """

    KINGPIN = "KINGPIN"
    HANDLER = "HANDLER"
    MULE = "MULE"
    OPERATOR = "OPERATOR"
    VICTIM = "VICTIM"
    UNKNOWN = "UNKNOWN"


class RoleScore(BaseModel):
    """
    Role indicator for a single node.

    node_id : str       – canonical node id (matches Node.id)
    role    : Role      – the highest-scoring role indicator
    score   : float     – indicator strength in [0.0, 1.0]; 0 = no evidence,
                          1 = all documented indicators present.
                          This is NOT a probability of guilt.
    why     : list[str] – evidence-backed reasons, one item per fired indicator.
                          Every item must correspond to actual graph evidence.
                          Generic text not supported by the graph is forbidden.
    """

    node_id: str
    role: Role
    score: float = Field(..., ge=0.0, le=1.0)
    why: list[str] = Field(default_factory=list)


class HierarchyLevel(BaseModel):
    """
    One level in the organisational hierarchy (architecture.md §2.5).

    level_index : int       – 0 = top (Kingpin), ascending toward victims
    role        : Role      – role shared by nodes at this level
    node_ids    : list[str] – canonical node ids at this level
    """

    level_index: int = Field(..., ge=0)
    role: Role
    node_ids: list[str]


class HierarchyResult(BaseModel):
    """
    Complete hierarchy and role-scoring output for a case.

    Matches the architecture.md §2.5 AnalysisResult structure:

        "roles":     [...RoleScore...]
        "hierarchy": {"levels": [[...], [...], ...]}

    case_id    : str                – matches ResolvedGraph.case_id
    roles      : list[RoleScore]    – one entry per scored node
    levels     : list[list[str]]    – hierarchy levels, index 0 = top
                                      (KINGPIN → HANDLER → MULE → VICTIM)
                                      Each inner list is the node_ids at that
                                      level, sorted for determinism.
                                      Only levels with at least one node are
                                      included; absent evidence → absent level.
    """

    case_id: str
    roles: list[RoleScore] = Field(default_factory=list)
    levels: list[list[str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pattern classification output models  (appended below HierarchyResult)
# ---------------------------------------------------------------------------


class PatternType(str, Enum):
    """
    Fraud pattern types documented in architecture.md §2.6.

    Assigned to a case (not a single node) based on graph-wide evidence.
    These are analytical findings — NOT accusations of guilt.
    """

    SIM_SWAP = "SIM_SWAP"
    MULE_LAYERING = "MULE_LAYERING"
    VISHING = "VISHING"
    PHISHING_KYC = "PHISHING_KYC"
    INVESTMENT_TASK = "INVESTMENT_TASK"


class PatternMatch(BaseModel):
    """
    A single detected fraud pattern for a case.

    type       : PatternType  – one of the five architecture-documented patterns
    confidence : float        – indicator-based score in [0.0, 1.0]
                                score = fired_indicators / total_indicators
                                NOT an LLM probability or subjective judgement
    reasons    : list[str]    – evidence-backed reasons, one per fired indicator.
                                Every item must correspond to actual graph/metric
                                evidence. Generic text without backing is forbidden.
    """

    type: PatternType
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class PatternResult(BaseModel):
    """
    Complete pattern classification result for a case.

    case_id  : str                – matches ResolvedGraph.case_id
    patterns : list[PatternMatch] – patterns whose confidence >= MIN_CONFIDENCE,
                                    sorted by confidence descending.
                                    Empty list when no pattern reaches threshold.
    """

    case_id: str
    patterns: list[PatternMatch] = Field(default_factory=list)
