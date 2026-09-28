"""
backend/analysis/pipeline.py

Full analysis pipeline runner.

CONTRACT:
  Input:  ResolvedGraph  (backend/schemas/entities.py)
  Output: AnalysisResult (backend/schemas/result.py)

Pipeline steps (all deterministic Python + NetworkX — no LLM):
  1. build_graph        → nx.MultiDiGraph
  2. compute_metrics    → MetricResult
  3. detect_communities → CommunityResult
  4. score_hierarchy    → HierarchyResult
  5. classify_patterns  → PatternResult
  6. assemble           → AnalysisResult

IBM × Bob boundary
------------------
Bob is NOT called here.  This module performs only deterministic graph
analytics.  Bob is called upstream (extraction → bob_client.py) and
downstream (brief generation → reports/brief_builder.py).

Timeline construction
---------------------
The pipeline extracts timeline events from TRANSFERRED_TO edge timestamps
present in the graph.  Events are sorted chronologically.  No event is
invented; only timestamps found in edge attrs["ts"] are used.

Totals computation
------------------
loss_inr = sum of in_amount for all VICTIM-role nodes
victims  = count of VICTIM-role nodes
mules    = count of MULE-role nodes
operators= count of OPERATOR-role nodes
handlers = count of HANDLER-role nodes
"""

from __future__ import annotations

import time
from typing import Optional

import networkx as nx

from backend.analysis.communities import detect_communities
from backend.analysis.graph_builder import build_graph
from backend.analysis.hierarchy import score_hierarchy
from backend.analysis.metrics import compute_metrics
from backend.analysis.pattern_classifier import classify_patterns
from backend.schemas.analysis import Role
from backend.schemas.entities import ResolvedGraph
from backend.schemas.result import AnalysisResult, TimelineEvent, Totals


def _extract_timeline(G: nx.MultiDiGraph) -> list[TimelineEvent]:
    """
    Build a chronological list of timeline events from TRANSFERRED_TO
    and CALLED edges that carry a ts attribute.

    Only timestamps present in edge attrs are used.  No events are invented.
    """
    events: list[tuple[str, str]] = []

    for u, v, d in G.edges(data=True):
        etype = d.get("type", "")
        ts_raw = d.get("attrs", {}).get("ts")
        if not ts_raw:
            continue
        ts = str(ts_raw)
        label_u = G.nodes[u].get("label", u)
        label_v = G.nodes[v].get("label", v)
        if etype == "TRANSFERRED_TO":
            amount = d.get("attrs", {}).get("amount")
            if amount is not None:
                event_text = (
                    f"Transfer of {amount:.0f} INR from {label_u} to {label_v}"
                )
            else:
                event_text = f"Transfer from {label_u} to {label_v}"
            events.append((ts, event_text))
        elif etype == "CALLED":
            events.append((ts, f"Call from {label_u} to {label_v}"))

    # Sort by timestamp string (ISO-8601 sorts lexicographically)
    events.sort(key=lambda x: x[0])
    return [TimelineEvent(ts=ts, event=event) for ts, event in events]


def _compute_totals(
    G: nx.MultiDiGraph,
    hierarchy_result,
    metrics_result,
) -> Totals:
    """
    Compute aggregate totals from hierarchy roles and metrics.
    Only uses evidence present in the graph and metric results.
    """
    from backend.schemas.analysis import NodeMetrics

    role_map = {rs.node_id: rs.role for rs in hierarchy_result.roles}
    metrics_map = {nm.node_id: nm for nm in metrics_result.nodes}

    victim_count = sum(1 for r in role_map.values() if r == Role.VICTIM)
    mule_count = sum(1 for r in role_map.values() if r == Role.MULE)
    operator_count = sum(1 for r in role_map.values() if r == Role.OPERATOR)
    handler_count = sum(1 for r in role_map.values() if r == Role.HANDLER)

    # loss_inr = sum of out_amount for VICTIM-role nodes (funds they sent out)
    loss_inr: Optional[float] = None
    for node_id, role in role_map.items():
        if role == Role.VICTIM:
            nm = metrics_map.get(node_id)
            if nm and nm.out_amount is not None:
                loss_inr = (loss_inr or 0.0) + nm.out_amount

    return Totals(
        loss_inr=loss_inr,
        victims=victim_count if victim_count > 0 else None,
        mules=mule_count if mule_count > 0 else None,
        operators=operator_count if operator_count > 0 else None,
        handlers=handler_count if handler_count > 0 else None,
    )


def run_pipeline(resolved: ResolvedGraph) -> AnalysisResult:
    """
    Execute the complete analysis pipeline on a ResolvedGraph.

    Parameters
    ----------
    resolved : ResolvedGraph
        Validated, deduplicated entity graph from the resolver.

    Returns
    -------
    AnalysisResult — fully populated, Pydantic-validated, JSON-serialisable.

    Raises
    ------
    pydantic.ValidationError if the resolved graph fails schema validation.
    ValueError if an edge references an unknown node.
    """
    # Step 1 — Build graph
    G = build_graph(resolved)

    # Step 2 — Metrics
    metrics = compute_metrics(G)

    # Step 3 — Communities
    communities = detect_communities(G)

    # Step 4 — Hierarchy / role scoring
    hierarchy = score_hierarchy(G, metrics)

    # Step 5 — Pattern classification
    patterns = classify_patterns(G, metrics, hierarchy)

    # Step 6 — Assemble AnalysisResult
    primary = patterns.patterns[0] if patterns.patterns else None
    timeline = _extract_timeline(G)
    totals = _compute_totals(G, hierarchy, metrics)

    return AnalysisResult(
        case_id=resolved.case_id,
        primary_pattern=primary,
        all_patterns=patterns.patterns,
        roles=hierarchy.roles,
        levels=hierarchy.levels,
        totals=totals,
        timeline=timeline,
        metrics=metrics,
        communities=communities,
    )
