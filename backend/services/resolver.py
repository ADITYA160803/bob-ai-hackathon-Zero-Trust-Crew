"""
backend/services/resolver.py

Resolves an ExtractionResult (raw LLM/regex output) into a GraphPayload
with stable IDs, de-duplicated nodes, and re-wired edges.

Public API
──────────
resolve(result: ExtractionResult) -> GraphPayload

Steps
─────
1. Normalise each raw value by type.
2. Deduplicate: same normalised value + same type → one Node with merged
   sources list (no duplicates in the list).
3. Assign stable IDs per type:
     PHONE       → PH_<normalised digits>
     BANK_ACCOUNT→ BA_<normalised digits>
     UPI_ID      → UPI_<normalised handle, @ replaced with _at_>
     DEVICE      → DEV_<imei digits>
     IP          → IP_<ip with dots replaced by _>
     PERSON      → PE_<slug of first value seen>
     LOCATION    → LOC_<slug of first value seen>
4. People: do NOT auto-merge. Detect name variants (same first word,
   Levenshtein-like simple prefix check) and store as attrs.name_variants.
5. Re-wire RawEdge.source_value / target_value → stable node IDs.
6. Drop duplicate edges (same source+target+type); keep all evidence refs.
7. Drop edges whose endpoint has no matching node; log a warning.
8. Assign edge IDs: E1, E2, …

Masking helper
──────────────
mask(value) -> str   returns "XXXXXX<last 4 chars>" for display; never
                     stored in the graph or the ID.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from backend.schemas.entities import Edge, EdgeType, Node, NodeType, RawEdge, RawNode
from backend.schemas.graph import ExtractionResult, GraphPayload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Display masking (never stored in IDs or graph)
# ---------------------------------------------------------------------------

def mask(value: str) -> str:
    """Return 'XXXXXX<last 4>' for display. Input unchanged internally."""
    clean = re.sub(r"[\s\-]", "", value)
    suffix = clean[-4:] if len(clean) >= 4 else clean
    return f"XXXXXX{suffix}"


# ---------------------------------------------------------------------------
# Normalisation per type
# ---------------------------------------------------------------------------

def _norm_phone(v: str) -> str:
    """Strip spaces, dashes, leading +91; keep digits only."""
    v = re.sub(r"[\s\-]", "", v)
    if v.startswith("+91"):
        v = v[3:]
    return re.sub(r"\D", "", v)


def _norm_account(v: str) -> str:
    """Strip all spaces."""
    return re.sub(r"\s", "", v)


def _norm_upi(v: str) -> str:
    """Lowercase."""
    return v.strip().lower()


def _norm_imei(v: str) -> str:
    """Digits only."""
    return re.sub(r"\D", "", v)


def _norm_ip(v: str) -> str:
    return v.strip()


def _slug(v: str) -> str:
    """Lowercase, replace non-alnum with underscore, collapse runs."""
    s = re.sub(r"[^a-z0-9]+", "_", v.strip().lower())
    return s.strip("_") or "x"


_NORMALISE_BY_TYPE: dict[NodeType, Any] = {
    NodeType.PHONE: _norm_phone,
    NodeType.BANK_ACCOUNT: _norm_account,
    NodeType.UPI_ID: _norm_upi,
    NodeType.DEVICE: _norm_imei,
    NodeType.IP: _norm_ip,
    NodeType.PERSON: lambda v: v.strip(),      # no merge — keep original
    NodeType.LOCATION: lambda v: v.strip().lower(),
}


def _normalise_value(node_type: NodeType, value: str) -> str:
    fn = _NORMALISE_BY_TYPE.get(node_type, str.strip)
    return fn(value)


# ---------------------------------------------------------------------------
# Stable ID generation
# ---------------------------------------------------------------------------

def _make_id(node_type: NodeType, norm_value: str) -> str:
    if node_type == NodeType.PHONE:
        return f"PH_{norm_value}"
    if node_type == NodeType.BANK_ACCOUNT:
        return f"BA_{norm_value}"
    if node_type == NodeType.UPI_ID:
        handle = norm_value.replace("@", "_at_")
        return f"UPI_{handle}"
    if node_type == NodeType.DEVICE:
        return f"DEV_{norm_value}"
    if node_type == NodeType.IP:
        safe = norm_value.replace(".", "_")
        return f"IP_{safe}"
    if node_type == NodeType.PERSON:
        return f"PE_{_slug(norm_value)}"
    if node_type == NodeType.LOCATION:
        return f"LOC_{_slug(norm_value)}"
    return f"NODE_{_slug(norm_value)}"


# ---------------------------------------------------------------------------
# Label generation (human-readable display)
# ---------------------------------------------------------------------------

def _make_label(node_type: NodeType, raw_value: str) -> str:
    """Return a short display label. Phones get spaced groups; others as-is."""
    if node_type == NodeType.PHONE:
        digits = _norm_phone(raw_value)
        if len(digits) == 10:
            return f"{digits[:5]} {digits[5:]}"
    return raw_value


# ---------------------------------------------------------------------------
# Name-variant detection (PERSON only, no auto-merge)
# ---------------------------------------------------------------------------

def _share_first_word(a: str, b: str) -> bool:
    """True if both names share the same first word (case-insensitive)."""
    def _first(s: str) -> str:
        return s.strip().split()[0].lower() if s.strip() else ""
    return bool(_first(a)) and _first(a) == _first(b)


# ---------------------------------------------------------------------------
# Main resolve function
# ---------------------------------------------------------------------------

def _resolve_extraction(result: ExtractionResult) -> GraphPayload:
    """
    Convert an ExtractionResult into a de-duplicated, ID-stable GraphPayload.
    """
    # -----------------------------------------------------------------
    # Step 1 & 2: group raw nodes by (type, normalised_value)
    # -----------------------------------------------------------------
    # key  → (node_type, norm_value)
    # value→ list of raw values seen + all source evidence refs
    grouped: dict[tuple[NodeType, str], dict[str, Any]] = {}

    for rn in result.nodes:
        norm = _normalise_value(rn.type, rn.value)
        key = (rn.type, norm)
        if key not in grouped:
            grouped[key] = {
                "type": rn.type,
                "norm": norm,
                "first_raw": rn.value,
                "attrs": dict(rn.attrs),
                "sources": [],
            }
        src = rn.evidence
        if src not in grouped[key]["sources"]:
            grouped[key]["sources"].append(src)

    # -----------------------------------------------------------------
    # Step 3: build Node objects with stable IDs
    # -----------------------------------------------------------------
    nodes: list[Node] = []
    # raw_value → stable node ID  (for edge re-wiring)
    raw_to_id: dict[str, str] = {}
    # norm_key → stable node ID
    norm_to_id: dict[tuple[NodeType, str], str] = {}

    for key, info in grouped.items():
        node_type, norm = key
        node_id = _make_id(node_type, norm)
        label = _make_label(node_type, info["first_raw"])
        nodes.append(
            Node(
                id=node_id,
                type=node_type,
                label=label,
                attrs=info["attrs"],
                sources=info["sources"],
            )
        )
        norm_to_id[key] = node_id
        # map the first raw value; additional raw values mapped below

    # Build raw_value → id map from every original RawNode
    for rn in result.nodes:
        norm = _normalise_value(rn.type, rn.value)
        key = (rn.type, norm)
        if key in norm_to_id:
            raw_to_id[rn.value] = norm_to_id[key]

    # -----------------------------------------------------------------
    # Step 4: flag PERSON name variants (no auto-merge)
    # -----------------------------------------------------------------
    person_nodes = [n for n in nodes if n.type == NodeType.PERSON]
    for i, pa in enumerate(person_nodes):
        variants = [
            pb.label for j, pb in enumerate(person_nodes)
            if j != i and _share_first_word(pa.label, pb.label)
        ]
        if variants:
            existing = list(pa.attrs.get("name_variants", []))
            merged = list(dict.fromkeys(existing + variants))
            # model_copy produces a new object; nodes list holds references
            nodes[nodes.index(pa)] = pa.model_copy(
                update={"attrs": {**pa.attrs, "name_variants": merged}}
            )

    # -----------------------------------------------------------------
    # Step 5 & 6 & 7: re-wire edges, deduplicate, drop dangling
    # -----------------------------------------------------------------
    # dedup key → (source_id, target_id, edge_type)
    edge_map: dict[tuple[str, str, EdgeType], dict[str, Any]] = {}

    for re_ in result.edges:
        src_id = raw_to_id.get(re_.source_value)
        tgt_id = raw_to_id.get(re_.target_value)

        if src_id is None:
            logger.warning(
                "Edge %s->%s: source_value %r has no matching node; dropping.",
                re_.source_value, re_.target_value, re_.source_value,
            )
            continue
        if tgt_id is None:
            logger.warning(
                "Edge %s->%s: target_value %r has no matching node; dropping.",
                re_.source_value, re_.target_value, re_.target_value,
            )
            continue

        dedup_key = (src_id, tgt_id, re_.type)
        if dedup_key not in edge_map:
            edge_map[dedup_key] = {
                "source": src_id,
                "target": tgt_id,
                "type": re_.type,
                "attrs": dict(re_.attrs),
                "evidence": re_.evidence,
            }
        else:
            # Keep evidence from all occurrences (store as semicolon-separated)
            existing_ev = edge_map[dedup_key]["evidence"]
            if re_.evidence not in existing_ev:
                edge_map[dedup_key]["evidence"] += f"; {re_.evidence}"

    # -----------------------------------------------------------------
    # Step 8: assign stable edge IDs
    # -----------------------------------------------------------------
    edges: list[Edge] = []
    for idx, info in enumerate(edge_map.values(), start=1):
        edges.append(
            Edge(
                id=f"E{idx}",
                source=info["source"],
                target=info["target"],
                type=info["type"],
                attrs=info["attrs"],
                evidence=info["evidence"],
            )
        )

    return GraphPayload(nodes=nodes, edges=edges)


def resolve(case_id_or_result, raw_nodes=None, raw_edges=None):
    """
    Unified resolve supporting two calling conventions:

    1. resolve(extraction_result: ExtractionResult) -> GraphPayload
       Original form used by the pipeline.

    2. resolve(case_id: str, raw_nodes: list[dict], raw_edges: list[dict]) -> ResolvedGraph
       Contract-test form: pass already-resolved Node/Edge dicts directly.
    """
    if isinstance(case_id_or_result, str):
        # New form: resolve(case_id, raw_nodes, raw_edges) -> ResolvedGraph
        from backend.schemas.entities import ResolvedGraph
        nodes = [Node.model_validate(n) for n in (raw_nodes or [])]
        edges = [Edge.model_validate(e) for e in (raw_edges or [])]
        return ResolvedGraph(case_id=case_id_or_result, nodes=nodes, edges=edges)
    else:
        # Original form: resolve(ExtractionResult) -> GraphPayload
        return _resolve_extraction(case_id_or_result)
