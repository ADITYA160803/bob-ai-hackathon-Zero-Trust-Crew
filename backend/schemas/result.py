"""
backend/schemas/result.py

Top-level AnalysisResult schema matching architecture.md §2.5.

This is the final output of the full pipeline and the object that:
  - the API returns
  - the brief generator consumes
  - sample_analysis.json conforms to
  - the frontend dashboard reads

Do NOT duplicate Node, Edge, ResolvedGraph, or individual analytics models.
Import them from their canonical locations.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.schemas.analysis import (
    CommunityResult,
    HierarchyResult,
    MetricResult,
    PatternMatch,
    PatternResult,
    RoleScore,
)


class TimelineEvent(BaseModel):
    """One event in the fraud timeline (architecture.md §2.5 AnalysisResult)."""

    ts: str = Field(..., description="ISO-8601 timestamp string")
    event: str = Field(..., description="Human-readable event description")


class Totals(BaseModel):
    """Aggregate summary figures for the case."""

    loss_inr: Optional[float] = None
    victims: Optional[int] = None
    mules: Optional[int] = None
    operators: Optional[int] = None
    handlers: Optional[int] = None


class AnalysisResult(BaseModel):
    """
    Complete analysis output for a single case.

    Matches architecture.md §2.5:

    {
      "pattern":   { "type", "secondary", "confidence", "reasons" },
      "roles":     [{ "node_id", "role", "score", "why" }],
      "hierarchy": { "levels": [[...], [...]] },
      "totals":    { "loss_inr", "victims", "mules" },
      "timeline":  [{ "ts", "event" }]
    }

    Plus extended fields for the full analytics output.

    case_id       : str           — matches ResolvedGraph.case_id
    primary_pattern: Optional[PatternMatch] — highest-confidence pattern
    all_patterns  : list[PatternMatch]      — all detected patterns
    roles         : list[RoleScore]         — per-node role indicators
    levels        : list[list[str]]         — hierarchy levels (index 0 = top)
    totals        : Totals                  — aggregate figures
    timeline      : list[TimelineEvent]     — chronological events
    metrics       : Optional[MetricResult]  — detailed per-node metrics
    communities   : Optional[CommunityResult] — community detection result
    """

    case_id: str
    primary_pattern: Optional[PatternMatch] = None
    all_patterns: list[PatternMatch] = Field(default_factory=list)
    roles: list[RoleScore] = Field(default_factory=list)
    levels: list[list[str]] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    metrics: Optional[MetricResult] = None
    communities: Optional[CommunityResult] = None
