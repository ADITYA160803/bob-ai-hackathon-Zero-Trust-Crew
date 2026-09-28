"""
backend/analysis/communities.py

Graph analytics — community detection.

CONTRACT INPUT : nx.MultiDiGraph  (from graph_builder.build_graph)
CONTRACT OUTPUT: CommunityResult  (backend/schemas/analysis.py)

No LLM / AI call is made here. All calculations are deterministic Python +
NetworkX. IBM × Bob is the only permitted AI layer.

Algorithm
---------
networkx.algorithms.community.greedy_modularity_communities
as specified in architecture.md §2.2.

MultiDiGraph → undirected projection
--------------------------------------
greedy_modularity_communities requires an undirected, simple Graph.
The MultiDiGraph must be projected before detection.

Steps:
  1. G.to_undirected()  →  nx.MultiGraph   (directed edges become undirected;
                            parallel edges in opposite directions are merged)
  2. nx.Graph(multigraph) → nx.Graph  (collapses parallel edges into one)

Why collapse parallel edges (step 2)?
  - greedy_modularity_communities requires a simple Graph (no multi-edges).
  - Collapsing parallel edges to a single undirected edge is the standard
    projection for community detection; it preserves node connectivity without
    artificially inflating the modularity of nodes that happen to share many
    parallel edges.
  - Node identity is fully preserved — only duplicate edges are collapsed.
  - This is documented in graph_builder.py module docstring.

Output
------
Communities are sorted by size descending so the most significant cluster
appears first.  Each community has a 0-based community_id reflecting this
order.  community_id is stable for the same graph but not globally stable
across different runs with different graphs.

A community is a structural cluster — it does NOT imply guilt, organisational
role, or any investigative conclusion.
"""

from __future__ import annotations

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities

from backend.schemas.analysis import Community, CommunityResult


def detect_communities(G: nx.MultiDiGraph) -> CommunityResult:
    """
    Detect communities in the fraud network using greedy modularity.

    Parameters
    ----------
    G : nx.MultiDiGraph
        Output of graph_builder.build_graph().

    Returns
    -------
    CommunityResult — Pydantic-validated list of Community objects, sorted
    by size descending.

    Edge cases
    ----------
    * Empty graph (0 nodes)  → returns empty CommunityResult.
    * Single node            → returns one community of size 1.
    * Fully disconnected     → each isolated node is its own community.
    * Parallel edges between the same pair → collapsed to one undirected edge
      before detection; node identity is preserved.
    """
    case_id: str = G.graph.get("case_id", "unknown")

    if G.number_of_nodes() == 0:
        return CommunityResult(case_id=case_id, communities=[])

    # ── Step 1: directed MultiDiGraph → undirected MultiGraph ────────────────
    undirected_multi: nx.MultiGraph = G.to_undirected()

    # ── Step 2: MultiGraph → simple Graph (collapse parallel edges) ──────────
    # greedy_modularity_communities requires a simple Graph.
    # nx.Graph(multigraph) keeps only the last parallel edge's attributes
    # between each pair, but since we only need structure for community
    # detection, attribute loss here is intentional and documented.
    simple: nx.Graph = nx.Graph(undirected_multi)

    # ── Step 3: run community detection ──────────────────────────────────────
    raw_communities = greedy_modularity_communities(simple)

    # ── Step 4: sort by size descending, assign 0-based ids ──────────────────
    sorted_comms = sorted(raw_communities, key=len, reverse=True)

    communities: list[Community] = [
        Community(
            community_id=idx,
            node_ids=sorted(comm),  # sort for determinism
            size=len(comm),
        )
        for idx, comm in enumerate(sorted_comms)
    ]

    return CommunityResult(
        case_id=case_id,
        communities=communities,
        method="greedy_modularity_communities",
    )
