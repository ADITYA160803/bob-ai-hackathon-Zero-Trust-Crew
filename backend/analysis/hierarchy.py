"""
backend/analysis/hierarchy.py

Deterministic role scoring and organisational hierarchy construction.

CONTRACT INPUT:
  G       : nx.MultiDiGraph  (from graph_builder.build_graph)
  metrics : MetricResult     (from metrics.compute_metrics)

CONTRACT OUTPUT:
  HierarchyResult            (backend/schemas/analysis.py)

No LLM / AI call is made here.  IBM × Bob is the only permitted AI layer.
All scoring is rule-based, deterministic Python + NetworkX.

===========================================================================
ROLES AND SCORING (architecture.md §2.6)
===========================================================================

Roles are RISK INDICATORS ONLY.  They are not conclusions of guilt.
All "why" reasons must correspond to actual graph/metric evidence.
If evidence is absent, the indicator is simply not fired.

Five roles are scored per node using independent rule sets.
The role with the highest computed score is assigned.
A node is labelled UNKNOWN if no role score exceeds UNKNOWN_THRESHOLD.

------ MULE ----------------------------------------------------------------
Architecture: "high fan-in + fast fan-out (pass-through ratio ~1,
               dwell time < 30 min)"

Indicators (one point each, fractional final score):
  A. transfer_fan_in  >= MULE_MIN_FAN_IN        (default 1)
  B. transfer_fan_out >= MULE_MIN_FAN_OUT        (default 1)
  C. pass_through_ratio is not None
     AND abs(pass_through_ratio - 1.0) <= MULE_PASS_THROUGH_TOLERANCE
     Tolerance = 0.25  (ratio in [0.75, 1.25])
     Rationale: "≈1" is not defined precisely in the architecture.
     0.25 is chosen to catch mules who skim a modest fee (<25%) while
     still forwarding the bulk of funds, which is the documented behaviour.
  D. min_dwell_sec is not None
     AND min_dwell_sec < MULE_DWELL_SEC_THRESHOLD   (default 1800 s = 30 min)

Score = (indicators_fired) / 4.0

------ VICTIM ---------------------------------------------------------------
Architecture: "funds flow out once to unknown account; receives OTP
               call/SMS; no onward flow"

Indicators:
  A. transfer_fan_out >= 1  (has at least one outgoing transfer)
  B. transfer_fan_in  == 0  (no incoming transfers — funds left, none received)
  C. out_degree_CALLED_in == CALLED edges where this node is RECEIVER
     i.e. this node received call/SMS (Operator→Victim direction)
  D. out_amount > 0  (positive outgoing transfer amount where available)
  E. transfer_fan_out == 1  (exactly one outgoing transfer = "once")

Score = (indicators_fired) / 5.0

Note: indicators A+B alone (out >= 1, in == 0) is a weak but minimal
victim signal.  C strengthens it.  E enforces "once".

------ OPERATOR --------------------------------------------------------------
Architecture: "high out-degree CALLED to many victims, shared devices,
               short calls"

Indicators:
  A. out_calls >= OPERATOR_MIN_CALLS  (default 2 outgoing CALLED edges)
  B. out_calls / max(total_out, 1) > 0.5  (calls dominate out-edges)
  C. shared_devices >= 1  (USES_DEVICE or SIM_IN_DEVICE shared with >= 1 other node)
  D. short_calls_present: any outgoing CALLED edge with attrs["duration_sec"] < 120

Score = (indicators_fired) / 4.0

Call duration is read from edge.attrs["duration_sec"]; absent = not fired.

------ HANDLER --------------------------------------------------------------
Architecture: "connects several mules/operators (high betweenness),
               receives partial cash-out"

Indicators:
  A. betweenness > HANDLER_BETWEENNESS_THRESHOLD  (default 0.1)
  B. transfer_fan_in  >= 1  (receives some transfers)
  C. transfer_fan_out >= 1  (forwards some transfers)
  D. pass_through_ratio is not None
     AND pass_through_ratio < HANDLER_PASS_THROUGH_CEIL  (default 0.9)
     i.e. keeps more than 10% — partial cash-out indicator

Score = (indicators_fired) / 4.0

------ KINGPIN --------------------------------------------------------------
Architecture: "terminal sink of largest share of funds, few direct victim
               contacts, high betweenness, contacted by handlers"

Indicators:
  A. transfer_fan_in  >= 1  (receives funds)
  B. transfer_fan_out == 0  (terminal sink — no onward transfers)
  C. in_amount is not None AND in_amount > 0
  D. in_fraction >= KINGPIN_IN_FRACTION_THRESHOLD  (default 0.3 = 30% of
     total network inflow)  — largest share of funds
  E. betweenness > KINGPIN_BETWEENNESS_THRESHOLD  (default 0.05)
  F. out_calls_to_victims == 0  (few direct victim contacts)
     Proxy: outgoing CALLED edges == 0

Score = (indicators_fired) / 6.0

===========================================================================
HIERARCHY CONSTRUCTION
===========================================================================

The hierarchy mirrors the architecture §2.5 example:
  levels[0] = KINGPIN nodes
  levels[1] = HANDLER nodes
  levels[2] = MULE nodes
  levels[3] = OPERATOR nodes
  levels[4] = VICTIM nodes

Only levels with at least one assigned node are included.
Node lists within each level are sorted for determinism.
Nodes with role UNKNOWN do not appear in the hierarchy levels list.

Total network inflow
--------------------
Used to compute Kingpin indicator D (in_fraction).
Defined as: sum of in_amount across ALL nodes that have in_amount > 0.
This approximates the total funds that entered the monitored network.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx

from backend.schemas.analysis import (
    HierarchyResult,
    MetricResult,
    NodeMetrics,
    Role,
    RoleScore,
)

# ---------------------------------------------------------------------------
# Tunable thresholds (all documented above)
# ---------------------------------------------------------------------------

MULE_MIN_FAN_IN: int = 1
MULE_MIN_FAN_OUT: int = 1
MULE_PASS_THROUGH_TOLERANCE: float = 0.25   # ratio ∈ [0.75, 1.25]
MULE_DWELL_SEC_THRESHOLD: float = 1800.0    # 30 minutes

OPERATOR_MIN_CALLS: int = 2
HANDLER_BETWEENNESS_THRESHOLD: float = 0.10
HANDLER_PASS_THROUGH_CEIL: float = 0.90

KINGPIN_IN_FRACTION_THRESHOLD: float = 0.30
KINGPIN_BETWEENNESS_THRESHOLD: float = 0.05

# A node is labelled UNKNOWN if its highest role score is below this value
UNKNOWN_THRESHOLD: float = 0.20

# Canonical hierarchy order for level construction
_LEVEL_ORDER: list[Role] = [
    Role.KINGPIN,
    Role.HANDLER,
    Role.MULE,
    Role.OPERATOR,
    Role.VICTIM,
]


# ---------------------------------------------------------------------------
# Helper — outgoing edge type counts
# ---------------------------------------------------------------------------

def _out_edge_type_count(G: nx.MultiDiGraph, node: str, edge_type: str) -> int:
    return sum(
        1 for _, _, d in G.out_edges(node, data=True)
        if d.get("type") == edge_type
    )


def _in_edge_type_count(G: nx.MultiDiGraph, node: str, edge_type: str) -> int:
    return sum(
        1 for _, _, d in G.in_edges(node, data=True)
        if d.get("type") == edge_type
    )


def _has_short_call(G: nx.MultiDiGraph, node: str, threshold_sec: float = 120.0) -> bool:
    """Return True if any outgoing CALLED edge has duration_sec < threshold."""
    for _, _, d in G.out_edges(node, data=True):
        if d.get("type") != "CALLED":
            continue
        dur = d.get("attrs", {}).get("duration_sec")
        if dur is not None:
            try:
                if float(dur) < threshold_sec:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def _shared_device_count(G: nx.MultiDiGraph, node: str) -> int:
    """
    Count device nodes (DEVICE, PHONE) that this node shares with at least
    one other node via USES_DEVICE or SIM_IN_DEVICE edges.

    A 'shared device' is a device node that has >= 2 incoming USES_DEVICE /
    SIM_IN_DEVICE edges (i.e. multiple people use/used it).
    """
    device_types = {"USES_DEVICE", "SIM_IN_DEVICE"}
    shared = 0
    for _, tgt, d in G.out_edges(node, data=True):
        if d.get("type") not in device_types:
            continue
        # Count how many nodes point to the same device
        in_count = sum(
            1 for _, _, d2 in G.in_edges(tgt, data=True)
            if d2.get("type") in device_types
        )
        if in_count >= 2:
            shared += 1
    return shared


# ---------------------------------------------------------------------------
# Individual role scorers
# ---------------------------------------------------------------------------

def _score_mule(nm: NodeMetrics) -> tuple[float, list[str]]:
    reasons: list[str] = []

    if nm.transfer_fan_in >= MULE_MIN_FAN_IN:
        reasons.append(
            f"Suspected indicator: transfer fan-in is {nm.transfer_fan_in} "
            f"(threshold >= {MULE_MIN_FAN_IN})"
        )
    if nm.transfer_fan_out >= MULE_MIN_FAN_OUT:
        reasons.append(
            f"Suspected indicator: transfer fan-out is {nm.transfer_fan_out} "
            f"(threshold >= {MULE_MIN_FAN_OUT})"
        )
    if nm.pass_through_ratio is not None and abs(nm.pass_through_ratio - 1.0) <= MULE_PASS_THROUGH_TOLERANCE:
        reasons.append(
            f"Pass-through ratio {nm.pass_through_ratio:.3f} is within "
            f"tolerance ±{MULE_PASS_THROUGH_TOLERANCE} of 1.0 "
            f"(possible mule fund-forwarding indicator)"
        )
    if nm.min_dwell_sec is not None and nm.min_dwell_sec < MULE_DWELL_SEC_THRESHOLD:
        reasons.append(
            f"Minimum transfer dwell time {nm.min_dwell_sec:.0f}s is below "
            f"{MULE_DWELL_SEC_THRESHOLD:.0f}s (30-minute mule indicator)"
        )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


def _score_victim(
    nm: NodeMetrics,
    G: nx.MultiDiGraph,
) -> tuple[float, list[str]]:
    """
    Hard prerequisite: node must have at least one outgoing transfer.
    A node with zero outgoing transfers cannot be a Victim under the
    architecture rule ("funds flow out once to unknown account").
    This prevents an isolated node with no edges from scoring as Victim
    via the absence-of-evidence "no incoming transfers" indicator.
    """
    if nm.transfer_fan_out < 1:
        return 0.0, []

    reasons: list[str] = []

    reasons.append(
        f"Suspected indicator: node has {nm.transfer_fan_out} outgoing "
        f"transfer(s) (possible victim fund-loss indicator)"
    )
    if nm.transfer_fan_in == 0:
        reasons.append(
            "No incoming transfers observed — funds left without receiving any "
            "(possible victim indicator)"
        )
    calls_received = _in_edge_type_count(G, nm.node_id, "CALLED")
    sms_received = _in_edge_type_count(G, nm.node_id, "SMS_SENT")
    if calls_received > 0 or sms_received > 0:
        reasons.append(
            f"Node received {calls_received} CALLED and {sms_received} SMS_SENT "
            f"edge(s) — possible OTP/vishing contact indicator"
        )
    if nm.out_amount is not None and nm.out_amount > 0:
        reasons.append(
            f"Outgoing transfer amount {nm.out_amount:.2f} INR recorded "
            f"(possible victim loss indicator)"
        )
    if nm.transfer_fan_out == 1:
        reasons.append(
            "Exactly one outgoing transfer — consistent with 'funds flow out once' "
            "victim pattern"
        )

    score = round(len(reasons) / 5.0, 8)
    return score, reasons


def _score_operator(
    nm: NodeMetrics,
    G: nx.MultiDiGraph,
) -> tuple[float, list[str]]:
    reasons: list[str] = []

    out_calls = _out_edge_type_count(G, nm.node_id, "CALLED")
    total_out = nm.out_degree

    if out_calls >= OPERATOR_MIN_CALLS:
        reasons.append(
            f"Suspected indicator: {out_calls} outgoing CALLED edge(s) "
            f"(threshold >= {OPERATOR_MIN_CALLS})"
        )
    if total_out > 0 and (out_calls / total_out) > 0.5:
        reasons.append(
            f"CALLED edges represent {out_calls}/{total_out} "
            f"({100*out_calls/total_out:.0f}%) of outgoing relationships "
            f"(calls dominate activity)"
        )
    shared = _shared_device_count(G, nm.node_id)
    if shared >= 1:
        reasons.append(
            f"Associated with {shared} device(s) shared with at least one other "
            f"node — possible shared-device indicator"
        )
    if _has_short_call(G, nm.node_id):
        reasons.append(
            "At least one outgoing CALLED edge has duration_sec < 120s "
            "(short-call operator indicator)"
        )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


def _score_handler(nm: NodeMetrics) -> tuple[float, list[str]]:
    reasons: list[str] = []

    if nm.betweenness > HANDLER_BETWEENNESS_THRESHOLD:
        reasons.append(
            f"Betweenness centrality {nm.betweenness:.4f} exceeds threshold "
            f"{HANDLER_BETWEENNESS_THRESHOLD} — possible network connector indicator"
        )
    if nm.transfer_fan_in >= 1:
        reasons.append(
            f"Receives {nm.transfer_fan_in} incoming transfer(s) — "
            f"possible partial cash-out recipient indicator"
        )
    if nm.transfer_fan_out >= 1:
        reasons.append(
            f"Forwards {nm.transfer_fan_out} outgoing transfer(s) — "
            f"possible handler fund-routing indicator"
        )
    if (
        nm.pass_through_ratio is not None
        and nm.pass_through_ratio < HANDLER_PASS_THROUGH_CEIL
    ):
        reasons.append(
            f"Pass-through ratio {nm.pass_through_ratio:.3f} < "
            f"{HANDLER_PASS_THROUGH_CEIL} — retains portion of funds "
            f"(possible partial cash-out indicator)"
        )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


def _score_kingpin(
    nm: NodeMetrics,
    G: nx.MultiDiGraph,
    total_network_inflow: float,
) -> tuple[float, list[str]]:
    """
    Hard prerequisites (both required, else score = 0):
      - transfer_fan_in >= 1  (must actually receive funds)
      - transfer_fan_out == 0 (terminal sink — no onward transfers)

    Without these gates an isolated node (no edges) would spuriously score
    Kingpin via absence-of-evidence signals ("no outgoing transfers",
    "no outgoing calls"), which would violate the evidence-backed rule.
    """
    if nm.transfer_fan_in < 1 or nm.transfer_fan_out != 0:
        return 0.0, []

    reasons: list[str] = []

    # Both gates passed — record them as positive indicators
    reasons.append(
        f"Receives {nm.transfer_fan_in} incoming transfer(s)"
    )
    reasons.append(
        "No outgoing transfers — possible terminal fund-sink indicator"
    )
    if nm.in_amount is not None and nm.in_amount > 0:
        reasons.append(
            f"Total incoming transfer amount: {nm.in_amount:.2f} INR"
        )
        if total_network_inflow > 0:
            fraction = nm.in_amount / total_network_inflow
            if fraction >= KINGPIN_IN_FRACTION_THRESHOLD:
                reasons.append(
                    f"Receives {fraction*100:.1f}% of total monitored network "
                    f"inflow (threshold {KINGPIN_IN_FRACTION_THRESHOLD*100:.0f}%) "
                    f"— possible largest-share-of-funds indicator"
                )
    if nm.betweenness > KINGPIN_BETWEENNESS_THRESHOLD:
        reasons.append(
            f"Betweenness centrality {nm.betweenness:.4f} exceeds threshold "
            f"{KINGPIN_BETWEENNESS_THRESHOLD} — possible network-hub indicator"
        )
    out_calls = _out_edge_type_count(G, nm.node_id, "CALLED")
    if out_calls == 0:
        reasons.append(
            "No outgoing CALLED edges — few direct victim contacts indicator"
        )

    score = round(len(reasons) / 6.0, 8)
    return score, reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_hierarchy(
    G: nx.MultiDiGraph,
    metrics: MetricResult,
) -> HierarchyResult:
    """
    Score every node in the graph against the five role indicators and
    construct the organisational hierarchy.

    Parameters
    ----------
    G       : nx.MultiDiGraph — output of graph_builder.build_graph()
    metrics : MetricResult    — output of metrics.compute_metrics()

    Returns
    -------
    HierarchyResult — Pydantic-validated, JSON-serialisable.

    Notes
    -----
    * Roles are risk INDICATORS only, not conclusions of guilt.
    * Every "why" reason is tied to a specific graph measurement.
    * A node with no indicator score >= UNKNOWN_THRESHOLD is labelled UNKNOWN.
    * Nodes labelled UNKNOWN do not appear in hierarchy levels.
    """
    case_id: str = G.graph.get("case_id", "unknown")

    if not metrics.nodes:
        return HierarchyResult(case_id=case_id)

    # Build a lookup for fast NodeMetrics access
    metrics_by_id: dict[str, NodeMetrics] = {nm.node_id: nm for nm in metrics.nodes}

    # Total network inflow for Kingpin fraction calculation
    total_network_inflow: float = sum(
        nm.in_amount
        for nm in metrics.nodes
        if nm.in_amount is not None and nm.in_amount > 0
    )

    role_scores: list[RoleScore] = []

    for node_id in sorted(G.nodes):  # sorted for determinism
        nm = metrics_by_id.get(node_id)
        if nm is None:
            # Node exists in graph but has no metrics — skip
            continue

        # Score all five roles
        candidates: dict[Role, tuple[float, list[str]]] = {
            Role.MULE:     _score_mule(nm),
            Role.VICTIM:   _score_victim(nm, G),
            Role.OPERATOR: _score_operator(nm, G),
            Role.HANDLER:  _score_handler(nm),
            Role.KINGPIN:  _score_kingpin(nm, G, total_network_inflow),
        }

        # Pick the role with the highest score; ties broken by _LEVEL_ORDER priority
        best_role = Role.UNKNOWN
        best_score = 0.0
        best_reasons: list[str] = []

        for role in _LEVEL_ORDER:   # priority order: KINGPIN first
            score, reasons = candidates[role]
            if score > best_score or (
                score == best_score and role != Role.UNKNOWN and best_role == Role.UNKNOWN
            ):
                best_score = score
                best_role = role
                best_reasons = reasons

        if best_score < UNKNOWN_THRESHOLD:
            best_role = Role.UNKNOWN
            best_reasons = []

        role_scores.append(
            RoleScore(
                node_id=node_id,
                role=best_role,
                score=best_score,
                why=best_reasons,
            )
        )

    # Build hierarchy levels
    levels_map: dict[Role, list[str]] = {role: [] for role in _LEVEL_ORDER}
    for rs in role_scores:
        if rs.role in levels_map:
            levels_map[rs.role].append(rs.node_id)

    # Sort node_ids within each level for determinism
    for role in _LEVEL_ORDER:
        levels_map[role].sort()

    # Build levels list — only include non-empty levels, in hierarchy order
    levels: list[list[str]] = [
        levels_map[role]
        for role in _LEVEL_ORDER
        if levels_map[role]
    ]

    return HierarchyResult(
        case_id=case_id,
        roles=role_scores,
        levels=levels,
    )
