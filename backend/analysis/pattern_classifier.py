"""
backend/analysis/pattern_classifier.py

Deterministic fraud-pattern classification.

CONTRACT INPUTS:
  G        : nx.MultiDiGraph  (from graph_builder.build_graph)
  metrics  : MetricResult     (from metrics.compute_metrics)
  hierarchy: HierarchyResult  (from hierarchy.score_hierarchy)

CONTRACT OUTPUT:
  PatternResult               (backend/schemas/analysis.py)

No LLM / AI call is made here.  IBM × Bob is the only permitted AI layer.
All scoring is rule-based, deterministic Python + NetworkX.

===========================================================================
PATTERNS AND SCORING (architecture.md §2.6)
===========================================================================

Five patterns are supported.  Each is scored independently; a case may
match more than one pattern.

score = fired_indicators / total_indicators_for_pattern  (float in [0,1])

A pattern is reported only when score >= MIN_CONFIDENCE (default 0.40).
If no pattern reaches this threshold, PatternResult.patterns is empty.

Minimum confidence threshold choice
-------------------------------------
0.40 (2 out of 5, or 2 out of 4, etc.) was chosen as the minimum because:
  - A single indicator is ambiguous (1/4 = 0.25).
  - Two independent indicators give reasonable combined evidence.
  - Architecture does not specify a threshold; this is documented here.

=========================================================================
PATTERN 1 — SIM_SWAP
=========================================================================
Architecture: "SIM/IMEI change + OTP redirection + login from new device
               + rapid debit"

Indicators (4 total):
  A. At least one PHONE node with attr "sim_swapped_on" set
     (SIM change evidence in node attributes)
  B. At least one DEVICE node that appears in SIM_IN_DEVICE edges from
     multiple PHONE nodes (IMEI/device used by >1 SIM = SIM swap activity)
  C. At least one LOGGED_IN_FROM edge present
     (login from device — proxy for "login from new device" event)
  D. At least one TRANSFERRED_TO edge with attrs["ts"] present
     AND at least one PHONE node with attrs["sim_swapped_on"] present
     AND the earliest transfer happens within SIM_SWAP_RAPID_DEBIT_SEC
     of the earliest SIM swap timestamp
     (rapid debit after SIM swap)

=========================================================================
PATTERN 2 — MULE_LAYERING
=========================================================================
Architecture: "multi-hop chains, fan-in/fan-out"

Indicators (5 total):
  A. At least 2 TRANSFERRED_TO edges total (multi-hop possibility)
  B. Longest transfer chain >= MULE_LAYERING_MIN_HOPS (default 2)
     (a chain of length 2 means at least 3 accounts in sequence)
  C. At least one node has transfer_fan_in >= 1 AND transfer_fan_out >= 1
     (intermediate pass-through node)
  D. At least one node has pass_through_ratio != None
     AND abs(pass_through_ratio - 1.0) <= MULE_PASS_THROUGH_TOLERANCE (0.25)
  E. MULE role count >= 1 (hierarchy confirms mule presence)

=========================================================================
PATTERN 3 — VISHING
=========================================================================
Architecture: "many victim inbound calls from few numbers + OTP shared"

Indicators (4 total):
  A. Total CALLED edges >= VISHING_MIN_CALLS (default 3)
  B. Caller-to-callee ratio: unique callers <= VISHING_MAX_CALLER_RATIO
     of unique callees (few callers, many victims)
     Ratio threshold: caller_count / callee_count <= VISHING_CALLER_RATIO (0.5)
  C. At least one PERSON/PHONE node receives CALLED edges from a node
     that also made CALLED edges to other nodes (shared caller = operator)
  D. At least one SMS_SENT edge present (OTP delivery proxy)

=========================================================================
PATTERN 4 — PHISHING_KYC
=========================================================================
Architecture: "links/SMS to many + shared IPs/devices"

Indicators (4 total):
  A. SMS_SENT out-degree of at least one node >= PHISHING_MIN_SMS (default 2)
     (SMS sent to many)
  B. At least one IP or DEVICE node is the target of LOGGED_IN_FROM or
     USES_DEVICE from >= 2 different PERSON/PHONE nodes (shared IP/device)
  C. Unique targets of SMS_SENT edges >= PHISHING_MIN_SMS_TARGETS (default 2)
  D. At least one node with LOGGED_IN_FROM edges to an IP node
     that also has another LOGGED_IN_FROM from a different source node

=========================================================================
PATTERN 5 — INVESTMENT_TASK
=========================================================================
Architecture: "small early payouts then large deposits"

Indicators (4 total):
  A. At least 2 TRANSFERRED_TO edges with "amount" in attrs
  B. The earliest transfer(s) by timestamp are SMALLER than the latest:
     min_amount_early < max_amount_late
     where "early" = first 33% of timestamped transfers by time,
           "late"  = last  33% of timestamped transfers by time
  C. At least one early transfer amount < INVESTMENT_SMALL_AMOUNT (default 5000)
     (early payouts are small — recruitment / trust-building phase)
  D. At least one late transfer amount > INVESTMENT_LARGE_AMOUNT (default 50000)
     (large deposit in the exploitation phase)

If fewer than 2 timestamped transfers exist, indicators B-D return False.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import networkx as nx

from backend.schemas.analysis import (
    HierarchyResult,
    MetricResult,
    NodeMetrics,
    PatternMatch,
    PatternResult,
    PatternType,
    Role,
)

# ---------------------------------------------------------------------------
# Thresholds (all documented in module docstring above)
# ---------------------------------------------------------------------------

MIN_CONFIDENCE: float = 0.40            # minimum score to report a pattern

SIM_SWAP_RAPID_DEBIT_SEC: float = 3600.0  # 1 hour — rapid debit window

MULE_LAYERING_MIN_HOPS: int = 2         # minimum transfer-chain length
MULE_PASS_THROUGH_TOLERANCE: float = 0.25  # mirrors hierarchy.py

VISHING_MIN_CALLS: int = 3
VISHING_CALLER_RATIO: float = 0.5      # callers / callees

PHISHING_MIN_SMS: int = 2
PHISHING_MIN_SMS_TARGETS: int = 2

INVESTMENT_SMALL_AMOUNT: float = 5000.0
INVESTMENT_LARGE_AMOUNT: float = 50000.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _edge_iter(G: nx.MultiDiGraph, edge_type: str):
    """Yield (src, tgt, data) for every edge of the given type."""
    for u, v, d in G.edges(data=True):
        if d.get("type") == edge_type:
            yield u, v, d


def _parse_ts(ts_str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return UTC datetime or None."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _metrics_map(metrics: MetricResult) -> dict[str, NodeMetrics]:
    return {nm.node_id: nm for nm in metrics.nodes}


def _longest_transfer_chain(G: nx.MultiDiGraph) -> int:
    """
    Return the length (number of edges) of the longest directed path
    composed exclusively of TRANSFERRED_TO edges.

    Builds a DiGraph from transfer edges only, then finds the longest
    path if the subgraph is a DAG (acyclic).  Returns 0 for empty/cyclic.
    """
    transfer_edges = [(u, v) for u, v, d in G.edges(data=True)
                      if d.get("type") == "TRANSFERRED_TO"]
    if not transfer_edges:
        return 0
    dag = nx.DiGraph(transfer_edges)
    if not nx.is_directed_acyclic_graph(dag):
        # Cyclic — return number of distinct edges as a conservative estimate
        return len(transfer_edges)
    try:
        return nx.dag_longest_path_length(dag)
    except Exception:
        return 0


def _role_counts(hierarchy: HierarchyResult) -> dict[Role, int]:
    counts: dict[Role, int] = {}
    for rs in hierarchy.roles:
        counts[rs.role] = counts.get(rs.role, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Pattern scorers
# ---------------------------------------------------------------------------

def _classify_sim_swap(
    G: nx.MultiDiGraph,
    metrics: MetricResult,
) -> tuple[float, list[str]]:
    reasons: list[str] = []

    # A — PHONE node with sim_swapped_on attribute
    swapped_phones = [
        n for n, d in G.nodes(data=True)
        if d.get("type") == "PHONE" and d.get("attrs", {}).get("sim_swapped_on")
    ]
    if swapped_phones:
        reasons.append(
            f"{len(swapped_phones)} phone node(s) have 'sim_swapped_on' attribute "
            f"— SIM replacement evidence"
        )

    # B — DEVICE used by multiple SIMs (IMEI reuse / SIM swap to same device)
    device_sims: dict[str, set[str]] = {}
    for u, v, d in G.edges(data=True):
        if d.get("type") == "SIM_IN_DEVICE":
            device_sims.setdefault(v, set()).add(u)
    multi_sim_devices = {dev: sims for dev, sims in device_sims.items() if len(sims) >= 2}
    if multi_sim_devices:
        total_sims = sum(len(s) for s in multi_sim_devices.values())
        reasons.append(
            f"{len(multi_sim_devices)} device(s) associated with {total_sims} SIM(s) "
            f"via SIM_IN_DEVICE edges — possible IMEI/device reuse indicator"
        )

    # C — LOGGED_IN_FROM edge present
    login_edges = list(_edge_iter(G, "LOGGED_IN_FROM"))
    if login_edges:
        reasons.append(
            f"{len(login_edges)} LOGGED_IN_FROM edge(s) present — "
            f"login from device recorded"
        )

    # D — Rapid debit: earliest transfer close to SIM swap timestamp
    sim_swap_timestamps: list[datetime] = []
    for n, d in G.nodes(data=True):
        if d.get("type") == "PHONE":
            ts_raw = d.get("attrs", {}).get("sim_swapped_on")
            dt = _parse_ts(str(ts_raw)) if ts_raw else None
            if dt:
                sim_swap_timestamps.append(dt)

    transfer_timestamps: list[datetime] = []
    for _, _, d in _edge_iter(G, "TRANSFERRED_TO"):
        dt = _parse_ts(d.get("attrs", {}).get("ts"))
        if dt:
            transfer_timestamps.append(dt)

    if sim_swap_timestamps and transfer_timestamps:
        earliest_swap = min(sim_swap_timestamps)
        earliest_transfer = min(transfer_timestamps)
        gap_sec = (earliest_transfer - earliest_swap).total_seconds()
        if 0 <= gap_sec <= SIM_SWAP_RAPID_DEBIT_SEC:
            reasons.append(
                f"Earliest transfer is {gap_sec:.0f}s after earliest SIM swap "
                f"(within rapid-debit window of {SIM_SWAP_RAPID_DEBIT_SEC:.0f}s)"
            )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


def _classify_mule_layering(
    G: nx.MultiDiGraph,
    metrics: MetricResult,
    hierarchy: HierarchyResult,
) -> tuple[float, list[str]]:
    reasons: list[str] = []

    # A — At least 2 TRANSFERRED_TO edges
    transfer_count = sum(1 for _ in _edge_iter(G, "TRANSFERRED_TO"))
    if transfer_count >= 2:
        reasons.append(
            f"{transfer_count} TRANSFERRED_TO edge(s) present — "
            f"multi-transaction activity detected"
        )

    # B — Longest transfer chain >= min hops
    chain_len = _longest_transfer_chain(G)
    if chain_len >= MULE_LAYERING_MIN_HOPS:
        reasons.append(
            f"Longest transfer chain is {chain_len} hop(s) — "
            f"multi-hop layering indicator (threshold >= {MULE_LAYERING_MIN_HOPS})"
        )

    # C — At least one pass-through node (fan-in AND fan-out)
    pass_through_nodes = [
        nm.node_id for nm in metrics.nodes
        if nm.transfer_fan_in >= 1 and nm.transfer_fan_out >= 1
    ]
    if pass_through_nodes:
        reasons.append(
            f"{len(pass_through_nodes)} node(s) have both incoming and outgoing "
            f"transfers — intermediate pass-through accounts detected"
        )

    # D — At least one mule pass-through ratio
    ratio_nodes = [
        nm for nm in metrics.nodes
        if nm.pass_through_ratio is not None
        and abs(nm.pass_through_ratio - 1.0) <= MULE_PASS_THROUGH_TOLERANCE
    ]
    if ratio_nodes:
        ratios = [f"{nm.node_id}={nm.pass_through_ratio:.2f}" for nm in ratio_nodes[:3]]
        reasons.append(
            f"{len(ratio_nodes)} node(s) have pass-through ratio within "
            f"±{MULE_PASS_THROUGH_TOLERANCE} of 1.0 ({', '.join(ratios)}) — "
            f"possible mule fund-forwarding behaviour"
        )

    # E — Hierarchy confirms MULE role
    role_counts = _role_counts(hierarchy)
    mule_count = role_counts.get(Role.MULE, 0)
    if mule_count >= 1:
        reasons.append(
            f"Role scorer identified {mule_count} suspected mule node(s) in "
            f"the hierarchy"
        )

    score = round(len(reasons) / 5.0, 8)
    return score, reasons


def _classify_vishing(G: nx.MultiDiGraph) -> tuple[float, list[str]]:
    reasons: list[str] = []

    called_edges = list(_edge_iter(G, "CALLED"))
    sms_edges = list(_edge_iter(G, "SMS_SENT"))

    # A — Total CALLED edges >= threshold
    if len(called_edges) >= VISHING_MIN_CALLS:
        reasons.append(
            f"{len(called_edges)} CALLED edge(s) present — "
            f"high call volume indicator (threshold >= {VISHING_MIN_CALLS})"
        )

    # B — Few callers vs many callees
    callers = {u for u, _, _ in called_edges}
    callees = {v for _, v, _ in called_edges}
    if callers and callees and len(callees) > 0:
        ratio = len(callers) / len(callees)
        if ratio <= VISHING_CALLER_RATIO:
            reasons.append(
                f"{len(callers)} caller(s) contacted {len(callees)} callee(s) "
                f"(ratio {ratio:.2f} <= {VISHING_CALLER_RATIO}) — "
                f"few numbers calling many targets (vishing indicator)"
            )

    # C — Shared caller (same node calls multiple others)
    caller_outcount: dict[str, int] = {}
    for u, _, _ in called_edges:
        caller_outcount[u] = caller_outcount.get(u, 0) + 1
    shared_callers = [n for n, cnt in caller_outcount.items() if cnt >= 2]
    if shared_callers:
        reasons.append(
            f"{len(shared_callers)} node(s) made CALLED edges to 2+ different "
            f"targets — operator-style calling pattern"
        )

    # D — SMS_SENT present (OTP delivery proxy)
    if sms_edges:
        reasons.append(
            f"{len(sms_edges)} SMS_SENT edge(s) present — "
            f"possible OTP delivery indicator"
        )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


def _classify_phishing_kyc(G: nx.MultiDiGraph) -> tuple[float, list[str]]:
    reasons: list[str] = []

    sms_edges = list(_edge_iter(G, "SMS_SENT"))
    login_edges = list(_edge_iter(G, "LOGGED_IN_FROM"))
    device_edges = list(_edge_iter(G, "USES_DEVICE"))

    # A — High SMS out-degree from a single node
    sms_out_count: dict[str, int] = {}
    for u, _, _ in sms_edges:
        sms_out_count[u] = sms_out_count.get(u, 0) + 1
    high_sms_senders = [n for n, cnt in sms_out_count.items() if cnt >= PHISHING_MIN_SMS]
    if high_sms_senders:
        max_cnt = max(sms_out_count.values())
        reasons.append(
            f"{len(high_sms_senders)} node(s) sent SMS_SENT to {PHISHING_MIN_SMS}+ "
            f"targets (max {max_cnt}) — bulk SMS indicator"
        )

    # B — Shared IP/device (>= 2 sources log in to / use same node)
    shared_targets: dict[str, set[str]] = {}
    for u, v, _ in login_edges:
        shared_targets.setdefault(v, set()).add(u)
    for u, v, _ in device_edges:
        shared_targets.setdefault(v, set()).add(u)
    shared_infra = {t: srcs for t, srcs in shared_targets.items() if len(srcs) >= 2}
    if shared_infra:
        reasons.append(
            f"{len(shared_infra)} IP/device node(s) accessed by 2+ different "
            f"sources — shared infrastructure indicator"
        )

    # C — SMS sent to many unique targets
    sms_targets = {v for _, v, _ in sms_edges}
    if len(sms_targets) >= PHISHING_MIN_SMS_TARGETS:
        reasons.append(
            f"SMS_SENT edges reach {len(sms_targets)} unique target(s) — "
            f"mass-contact phishing indicator (threshold >= {PHISHING_MIN_SMS_TARGETS})"
        )

    # D — Multiple LOGGED_IN_FROM edges to same IP from different sources
    login_ip_sources: dict[str, set[str]] = {}
    for u, v, d in login_edges:
        if G.nodes.get(v, {}).get("type") == "IP":
            login_ip_sources.setdefault(v, set()).add(u)
    shared_ips = {ip: srcs for ip, srcs in login_ip_sources.items() if len(srcs) >= 2}
    if shared_ips:
        reasons.append(
            f"{len(shared_ips)} IP node(s) have LOGGED_IN_FROM edges from 2+ "
            f"different sources — shared IP access indicator"
        )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


def _classify_investment_task(G: nx.MultiDiGraph) -> tuple[float, list[str]]:
    reasons: list[str] = []

    # Collect all TRANSFERRED_TO edges with (amount, ts)
    timed_transfers: list[tuple[datetime, float]] = []
    all_amounts: list[float] = []

    for _, _, d in _edge_iter(G, "TRANSFERRED_TO"):
        attrs = d.get("attrs", {})
        raw_amt = attrs.get("amount")
        if raw_amt is None:
            continue
        try:
            amount = float(raw_amt)
        except (TypeError, ValueError):
            continue
        all_amounts.append(amount)
        ts = _parse_ts(attrs.get("ts"))
        if ts:
            timed_transfers.append((ts, amount))

    # A — At least 2 transfer edges with amounts
    if len(all_amounts) >= 2:
        reasons.append(
            f"{len(all_amounts)} TRANSFERRED_TO edge(s) with 'amount' attribute — "
            f"sufficient transaction data for pattern analysis"
        )

    # B, C, D require at least 2 timestamped transfers
    if len(timed_transfers) >= 2:
        timed_transfers.sort(key=lambda x: x[0])
        n = len(timed_transfers)
        third = max(1, n // 3)
        early_amounts = [amt for _, amt in timed_transfers[:third]]
        late_amounts = [amt for _, amt in timed_transfers[n - third:]]

        min_early = min(early_amounts) if early_amounts else None
        max_late = max(late_amounts) if late_amounts else None

        # B — Early amounts smaller than late amounts
        if min_early is not None and max_late is not None and min_early < max_late:
            reasons.append(
                f"Earlier transfers (min {min_early:.0f} INR) are smaller than "
                f"later transfers (max {max_late:.0f} INR) — "
                f"escalating-amount pattern detected"
            )

        # C — Early amounts include small payout
        if min_early is not None and min_early < INVESTMENT_SMALL_AMOUNT:
            reasons.append(
                f"Earliest transfer amount ({min_early:.0f} INR) is below "
                f"{INVESTMENT_SMALL_AMOUNT:.0f} INR threshold — "
                f"small initial payout indicator (trust-building phase)"
            )

        # D — Late amounts include large deposit
        if max_late is not None and max_late > INVESTMENT_LARGE_AMOUNT:
            reasons.append(
                f"Latest transfer amount ({max_late:.0f} INR) exceeds "
                f"{INVESTMENT_LARGE_AMOUNT:.0f} INR threshold — "
                f"large final deposit indicator (exploitation phase)"
            )

    score = round(len(reasons) / 4.0, 8)
    return score, reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_patterns(
    G: nx.MultiDiGraph,
    metrics: MetricResult,
    hierarchy: HierarchyResult,
) -> PatternResult:
    """
    Classify fraud patterns present in the fraud network graph.

    Parameters
    ----------
    G         : nx.MultiDiGraph  — output of graph_builder.build_graph()
    metrics   : MetricResult     — output of metrics.compute_metrics()
    hierarchy : HierarchyResult  — output of hierarchy.score_hierarchy()

    Returns
    -------
    PatternResult — patterns with confidence >= MIN_CONFIDENCE, sorted by
    confidence descending.  Empty patterns list if no pattern qualifies.

    Evidence requirement
    --------------------
    Every returned PatternMatch.reasons item is tied to a specific, measured
    graph property.  No reason is generated without actual supporting data.
    """
    case_id: str = G.graph.get("case_id", "unknown")

    if G.number_of_nodes() == 0:
        return PatternResult(case_id=case_id)

    # Score all patterns
    scorers = [
        (PatternType.SIM_SWAP,       lambda: _classify_sim_swap(G, metrics)),
        (PatternType.MULE_LAYERING,  lambda: _classify_mule_layering(G, metrics, hierarchy)),
        (PatternType.VISHING,        lambda: _classify_vishing(G)),
        (PatternType.PHISHING_KYC,   lambda: _classify_phishing_kyc(G)),
        (PatternType.INVESTMENT_TASK, lambda: _classify_investment_task(G)),
    ]

    matches: list[PatternMatch] = []
    for ptype, scorer in scorers:
        score, reasons = scorer()
        if score >= MIN_CONFIDENCE:
            matches.append(
                PatternMatch(
                    type=ptype,
                    confidence=score,
                    reasons=reasons,
                )
            )

    # Sort by confidence descending for determinism; tie-break by type name
    matches.sort(key=lambda m: (-m.confidence, m.type.value))

    return PatternResult(case_id=case_id, patterns=matches)
