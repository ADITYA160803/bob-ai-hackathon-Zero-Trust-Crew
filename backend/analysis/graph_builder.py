"""
backend/analysis/graph_builder.py

Builds a directed NetworkX graph from a ResolvedGraph.

CONTRACT INPUT:  ResolvedGraph     (backend/schemas/entities.py)
CONTRACT OUTPUT: nx.MultiDiGraph

Graph type decision — MultiDiGraph, not DiGraph
------------------------------------------------
nx.DiGraph silently overwrites an existing (source, target) edge when a
second edge between the same node pair is added.  This is unsafe for JAAL
because:

  1. The Edge schema defines 7 distinct semantic types (OWNS, CALLED,
     TRANSFERRED_TO, USES_DEVICE, SIM_IN_DEVICE, SMS_SENT, LOGGED_IN_FROM).
     A single node pair can legitimately carry more than one type in
     separate, independently evidenced events — e.g. a PERSON node can
     OWNS a BANK_ACCOUNT and also have a TRANSFERRED_TO edge to the same
     account from a different transaction record.

  2. rules.md §3.1: "Every output claim must trace to evidence.
     No evidence → don't display it."  Silently dropping a second edge
     would destroy its evidence reference, violating this rule.

  3. architecture.md §2.6 role-scoring requires counting all edges of
     each type independently (e.g. total funds transferred = sum of all
     TRANSFERRED_TO edges between a pair, not just the last one written).

Therefore nx.MultiDiGraph is the correct and required type.  Edge identity
is preserved via the edge `key` = Edge.id (str).

Analytics compatibility
-----------------------
All standard NetworkX analytics used by this project work on MultiDiGraph:
  - nx.degree_centrality, in_degree, out_degree   → MultiDiGraph supported
  - nx.betweenness_centrality                      → MultiDiGraph supported
  - nx.community.greedy_modularity_communities     → requires undirected;
      callers must pass nx.Graph(G) or G.to_undirected() — documented below
  - nx.weakly_connected_components                 → MultiDiGraph supported
  - nx.dag_longest_path (hierarchy)                → MultiDiGraph supported

Graph conventions
-----------------
* Node key  = Node.id  (str)
* Node attrs = {type, label, attrs, sources}   — all fields from Node model
* Edge key  = Edge.id  (str)   — unique per edge, never overwritten
* Edge attrs = {id, type, attrs, evidence}     — all fields from Edge model
  Note: source/target are already encoded as the nx edge endpoints.

Usage
-----
    from backend.schemas.entities import ResolvedGraph
    from backend.analysis.graph_builder import build_graph

    G = build_graph(resolved_graph)
    # For community detection (undirected projection):
    G_undirected = G.to_undirected()
"""

from __future__ import annotations

import networkx as nx

from backend.schemas.entities import ResolvedGraph


def build_graph(resolved: ResolvedGraph) -> nx.MultiDiGraph:
    """
    Convert a ResolvedGraph into a NetworkX MultiDiGraph.

    Parameters
    ----------
    resolved : ResolvedGraph
        Validated, deduplicated output of resolver.py.

    Returns
    -------
    nx.MultiDiGraph
        - graph attr  : case_id = resolved.case_id
        - node key    : Node.id (str)
        - node attrs  : type (str), label (str), attrs (dict), sources (list[str])
        - edge key    : Edge.id (str) — guarantees each evidence-backed
                        relationship is stored independently
        - edge attrs  : id (str), type (str), attrs (dict), evidence (str)

    Raises
    ------
    ValueError
        If an edge references a node id that is not present in the graph.
        This is a hard integrity check: every edge must connect known nodes.
    """
    G: nx.MultiDiGraph = nx.MultiDiGraph(case_id=resolved.case_id)

    # ── Add nodes ────────────────────────────────────────────────────────────
    for node in resolved.nodes:
        G.add_node(
            node.id,
            type=node.type.value,
            label=node.label,
            attrs=node.attrs,
            sources=node.sources,
        )

    # ── Validate and add edges ───────────────────────────────────────────────
    node_ids: set[str] = set(G.nodes)
    for edge in resolved.edges:
        if edge.source not in node_ids:
            raise ValueError(
                f"Edge '{edge.id}' references unknown source node '{edge.source}'"
            )
        if edge.target not in node_ids:
            raise ValueError(
                f"Edge '{edge.id}' references unknown target node '{edge.target}'"
            )
        G.add_edge(
            edge.source,
            edge.target,
            key=edge.id,
            id=edge.id,
            type=edge.type.value,
            attrs=edge.attrs,
            evidence=edge.evidence,
        )

    return G
