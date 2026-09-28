"""
backend/analysis/metrics.py

Graph analytics — node-level metrics.

CONTRACT INPUT : nx.MultiDiGraph  (from graph_builder.build_graph)
CONTRACT OUTPUT: MetricResult     (backend/schemas/analysis.py)

No LLM / AI call is made here. All calculations are deterministic Python +
NetworkX. IBM × Bob is the only permitted AI layer (used in extractor and
brief_builder only).

Metrics implemented
-------------------

1. Degree centrality
   NetworkX nx.degree_centrality(G) on a MultiDiGraph counts each parallel
   edge independently in the combined (in+out) degree, then divides by (n-1).
   This means degree_centrality CAN exceed 1.0 when a node has multiple
   parallel edges to the same neighbour (e.g. 2 parallel edges in a 2-node
   graph yields centrality = 2/(2-1) = 2.0).
   For a single-node graph, NetworkX returns 1.0 (not 0.0).
   The NodeMetrics schema intentionally removes the le=1.0 constraint for
   this reason — see backend/schemas/analysis.py.

2. Betweenness centrality
   nx.betweenness_centrality(G) on a MultiDiGraph.
   NetworkX treats each (u,v,key) edge independently during shortest-path
   calculation (it uses the underlying adjacency structure), so parallel
   edges do increase path options.  The result is normalised by default
   ((n-1)*(n-2) for directed graphs).
   For graphs with < 2 nodes, NetworkX returns 0.0 for all nodes.

3. Fan-in / Fan-out (all edges)
   G.in_degree(node)  → count of ALL incoming edges including parallel ones
   G.out_degree(node) → count of ALL outgoing edges including parallel ones
   This is the raw multi-edge degree, which is the correct count for
   Operator detection (high call out-degree) and general network position.

4. Transfer fan-in / Transfer fan-out
   Count only edges where type == "TRANSFERRED_TO".
   Parallel transfer edges are counted independently (each represents a
   separate evidenced transaction).

5. Pass-through ratio
   Definition chosen (not specified by architecture.md, documented here):
     ratio = out_amount / in_amount
   where:
     in_amount  = sum of edge.attrs["amount"] for all incoming TRANSFERRED_TO
     out_amount = sum of edge.attrs["amount"] for all outgoing TRANSFERRED_TO
   Only edges that carry an "amount" key are included; edges without an
   amount key are excluded from the sum (not invented).
   If in_amount is 0 or no amount data exists, ratio is None.
   A Mule indicator is ratio ≈ 1.0 (nearly all received funds re-forwarded).

   Rationale for amount-based (not edge-count-based) ratio:
   - architecture.md §2.6 specifies "terminal sink of largest share of funds"
     for Kingpin, implying fund amounts are the meaningful unit.
   - A mule routing 1×50,000 inbound → 1×49,000 outbound is a better
     indicator than 5×500 inbound → 1×2,400 outbound.

6. Transfer dwell time
   Definition: minimum elapsed time (seconds) between ANY incoming
   TRANSFERRED_TO edge and ANY outgoing TRANSFERRED_TO edge for a given node.
   "Minimum" is chosen because a mule's suspicious behaviour is the fastest
   re-forwarding event, not the average.
   Timestamps are read from edge.attrs["ts"] (ISO-8601 string, timezone-aware
   or naive). Missing or unparseable timestamps are skipped without error.
   Returns None if timestamps are insufficient (< 1 in OR < 1 out).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import networkx as nx

from backend.schemas.analysis import MetricResult, NodeMetrics

# Edge type constant — avoids magic strings throughout
_TRANSFER = "TRANSFERRED_TO"


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """
    Parse an ISO-8601 timestamp string.

    Returns a timezone-aware datetime (UTC if no tz info was present),
    or None if the string is missing, empty, or cannot be parsed.
    """
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _transfer_amounts(
    G: nx.MultiDiGraph, node: str, direction: str
) -> tuple[int, Optional[float]]:
    """
    Count TRANSFERRED_TO edges and sum amounts for a node in one direction.

    Parameters
    ----------
    G         : the graph
    node      : node id
    direction : "in"  → look at predecessors' edges to `node`
                "out" → look at edges from `node` to successors

    Returns
    -------
    (count, total_amount)
    count        – number of TRANSFERRED_TO edges in this direction
    total_amount – sum of "amount" values; None if no amount data at all
    """
    count = 0
    amounts: list[float] = []

    if direction == "in":
        edge_iter = G.in_edges(node, data=True, keys=True)
    else:
        edge_iter = G.out_edges(node, data=True, keys=True)

    for _src, _tgt, _key, data in edge_iter:
        if data.get("type") != _TRANSFER:
            continue
        count += 1
        raw = data.get("attrs", {}).get("amount")
        if raw is not None:
            try:
                amounts.append(float(raw))
            except (TypeError, ValueError):
                pass  # malformed amount — skip, do not invent

    total = sum(amounts) if amounts else None
    return count, total


def _transfer_timestamps(
    G: nx.MultiDiGraph, node: str, direction: str
) -> list[datetime]:
    """
    Collect parsed timestamps from TRANSFERRED_TO edges for a node.

    Only edges with valid, parseable ts values in attrs are returned.
    """
    dts: list[datetime] = []

    if direction == "in":
        edge_iter = G.in_edges(node, data=True, keys=True)
    else:
        edge_iter = G.out_edges(node, data=True, keys=True)

    for _src, _tgt, _key, data in edge_iter:
        if data.get("type") != _TRANSFER:
            continue
        ts_raw = data.get("attrs", {}).get("ts")
        dt = _parse_ts(ts_raw)
        if dt is not None:
            dts.append(dt)

    return dts


def _min_dwell_sec(
    in_times: list[datetime], out_times: list[datetime]
) -> Optional[float]:
    """
    Compute the minimum elapsed seconds between any incoming transfer timestamp
    and any outgoing transfer timestamp.

    Returns None if either list is empty (insufficient evidence).
    Returns None if all computed gaps are negative (outgoing before incoming —
    data anomaly, do not report a fabricated value).
    """
    if not in_times or not out_times:
        return None

    gaps: list[float] = []
    for t_in in in_times:
        for t_out in out_times:
            gap = (t_out - t_in).total_seconds()
            if gap >= 0:
                gaps.append(gap)

    return min(gaps) if gaps else None


def compute_metrics(G: nx.MultiDiGraph) -> MetricResult:
    """
    Compute all node-level metrics for the fraud network graph.

    Parameters
    ----------
    G : nx.MultiDiGraph
        Output of graph_builder.build_graph(). Must have case_id graph attr.

    Returns
    -------
    MetricResult — one NodeMetrics entry per node, Pydantic validated.

    Notes on NetworkX MultiDiGraph behaviour
    ----------------------------------------
    * nx.degree_centrality(G)      — uses combined in+out degree
    * nx.betweenness_centrality(G) — uses directed shortest paths
    * G.in_degree(n) / out_degree  — counts ALL parallel edges independently
    """
    case_id: str = G.graph.get("case_id", "unknown")
    n = G.number_of_nodes()

    if n == 0:
        return MetricResult(case_id=case_id, nodes=[])

    # ── Centrality (NetworkX handles MultiDiGraph natively) ──────────────────
    deg_centrality: dict[str, float] = nx.degree_centrality(G)
    betweenness: dict[str, float] = nx.betweenness_centrality(G)

    node_metrics: list[NodeMetrics] = []

    for node_id in G.nodes:
        # ── Degree ───────────────────────────────────────────────────────────
        in_deg: int = G.in_degree(node_id)
        out_deg: int = G.out_degree(node_id)

        # ── Transfer-specific fan-in/out and amounts ──────────────────────────
        tf_in, in_amount = _transfer_amounts(G, node_id, "in")
        tf_out, out_amount = _transfer_amounts(G, node_id, "out")

        # ── Pass-through ratio ────────────────────────────────────────────────
        pass_through: Optional[float] = None
        if in_amount is not None and in_amount > 0 and out_amount is not None:
            pass_through = out_amount / in_amount

        # ── Dwell time ────────────────────────────────────────────────────────
        in_times = _transfer_timestamps(G, node_id, "in")
        out_times = _transfer_timestamps(G, node_id, "out")
        dwell = _min_dwell_sec(in_times, out_times)

        node_metrics.append(
            NodeMetrics(
                node_id=node_id,
                degree_centrality=round(deg_centrality[node_id], 8),
                in_degree=in_deg,
                out_degree=out_deg,
                betweenness=round(betweenness[node_id], 8),
                transfer_fan_in=tf_in,
                transfer_fan_out=tf_out,
                in_amount=in_amount,
                out_amount=out_amount,
                pass_through_ratio=pass_through,
                min_dwell_sec=dwell,
            )
        )

    return MetricResult(case_id=case_id, nodes=node_metrics)
