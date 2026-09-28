"""
scripts/check_bob.py

Standalone connectivity check for the real Bob API.
NOT part of the pytest suite — tests remain fully mocked.

Usage
─────
    python scripts/check_bob.py

Prerequisites
─────────────
  1. Copy .env.example to .env and set BOB_API_KEY, BOB_API_URL, MODEL_NAME.
  2. Set FORCE_FALLBACK=0 (or remove it) in .env.
  3. BOB_API_URL must not contain "example.com".

The script sends ONE small mock chunk through bob_client.call_json, then:
  - Prints the raw parsed JSON.
  - Validates nodes against RawNode and edges against RawEdge.
  - Reports node/edge counts and whether the grounding check dropped anything.
  - On failure prints the exact error and the last line of logs/bob_calls.jsonl.

No new libraries are used beyond what the project already imports.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow running from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Do NOT set JAAL_TESTING — we need the real settings, including key validation.
# But we also don't want to crash if the key is missing; we print a nice message.
os.environ.setdefault("JAAL_TESTING", "0")


def _abort(msg: str) -> None:
    print(f"\n[ABORT] {msg}\n", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Import config (triggers key validation unless JAAL_TESTING=1)
    # ------------------------------------------------------------------
    try:
        from backend.config import settings
    except Exception as exc:
        _abort(
            f"Could not load settings: {exc}\n"
            "  → Copy .env.example to .env and fill in BOB_API_KEY, BOB_API_URL, MODEL_NAME."
        )

    # ------------------------------------------------------------------
    # 2. Pre-flight checks
    # ------------------------------------------------------------------
    if getattr(settings, "FORCE_FALLBACK", False):
        _abort(
            "FORCE_FALLBACK is ON — the script would never reach Bob.\n"
            "  → Set FORCE_FALLBACK=0 in your .env and try again."
        )

    api_key: str = getattr(settings, "BOB_API_KEY", "")
    if not api_key or api_key in ("", "your-bob-api-key-here", "PLACEHOLDER"):
        _abort(
            "BOB_API_KEY is missing or still a placeholder.\n"
            "  → Set BOB_API_KEY=<your real key> in your .env."
        )

    api_url: str = getattr(settings, "BOB_API_URL", "")
    if "example.com" in api_url:
        _abort(
            f"BOB_API_URL still points to example.com: {api_url!r}\n"
            "  → Set BOB_API_URL=<real endpoint> in your .env."
        )

    print("=" * 60)
    print("JAAL — Real Bob API connectivity check")
    print("=" * 60)
    print(f"  URL   : {api_url}")
    print(f"  Model : {settings.MODEL_NAME}")
    print(f"  Key   : {api_key[:6]}{'*' * max(0, len(api_key) - 6)}")
    print()

    # ------------------------------------------------------------------
    # 3. Build mock chunk and send it
    # ------------------------------------------------------------------
    from backend.services.parser import Chunk
    from backend.services.bob_client import call_json, BobUnavailableError
    from backend.services.extractor import _is_grounded
    from backend.schemas.entities import RawNode, RawEdge

    MOCK_TEXT = (
        "Mock case. Phone 98765 00001 sent Rs 45000 on 2023-03-02 11:42 "
        "from account 1234567890 to account 5678901234. IMEI 353456789012345."
    )
    SOURCE_REF = "check_bob#L1"

    # Construct the chunk object (used only for grounding checks below).
    chunk = Chunk(text=MOCK_TEXT, source_ref="check_bob", start_line=1, end_line=1)

    print(f"Sending mock chunk ({len(MOCK_TEXT)} chars) …")
    print(f"  source_ref: {SOURCE_REF}")
    print()

    try:
        result = call_json("extract.md", MOCK_TEXT, SOURCE_REF)
    except BobUnavailableError as exc:
        print(f"[FAIL] BobUnavailableError: {exc}", file=sys.stderr)
        _print_last_log_line(settings)
        sys.exit(1)
    except Exception as exc:
        print(f"[FAIL] Unexpected error: {exc}", file=sys.stderr)
        _print_last_log_line(settings)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Print raw JSON
    # ------------------------------------------------------------------
    print("Raw parsed JSON:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()

    # ------------------------------------------------------------------
    # 5. Validate nodes and edges against RawNode / RawEdge
    # ------------------------------------------------------------------
    raw_nodes = result.get("nodes", [])
    raw_edges = result.get("edges", [])

    valid_nodes: list[RawNode] = []
    invalid_node_count = 0
    for i, rn in enumerate(raw_nodes):
        try:
            valid_nodes.append(RawNode.model_validate(rn))
        except Exception as exc:
            print(f"  [WARN] Node {i} failed RawNode validation: {exc}")
            invalid_node_count += 1

    valid_edges: list[RawEdge] = []
    invalid_edge_count = 0
    for i, re_ in enumerate(raw_edges):
        try:
            valid_edges.append(RawEdge.model_validate(re_))
        except Exception as exc:
            print(f"  [WARN] Edge {i} failed RawEdge validation: {exc}")
            invalid_edge_count += 1

    print(f"Nodes : {len(raw_nodes)} returned  |  "
          f"{len(valid_nodes)} valid  |  {invalid_node_count} invalid")
    print(f"Edges : {len(raw_edges)} returned  |  "
          f"{len(valid_edges)} valid  |  {invalid_edge_count} invalid")
    print()

    # ------------------------------------------------------------------
    # 6. Grounding check — report what would be dropped
    # ------------------------------------------------------------------
    grounded_nodes = [n for n in valid_nodes if _is_grounded(n.value, MOCK_TEXT)]
    dropped_nodes  = [n for n in valid_nodes if not _is_grounded(n.value, MOCK_TEXT)]

    grounded_edges = [
        e for e in valid_edges
        if _is_grounded(e.source_value, MOCK_TEXT) and _is_grounded(e.target_value, MOCK_TEXT)
    ]
    dropped_edges = [
        e for e in valid_edges
        if not (_is_grounded(e.source_value, MOCK_TEXT) and _is_grounded(e.target_value, MOCK_TEXT))
    ]

    print(f"Grounding check:")
    print(f"  Nodes kept   : {len(grounded_nodes)}  |  dropped (invented): {len(dropped_nodes)}")
    print(f"  Edges kept   : {len(grounded_edges)}  |  dropped (invented): {len(dropped_edges)}")
    if dropped_nodes:
        for n in dropped_nodes:
            print(f"    [DROPPED node] type={n.type.value}  value={n.value!r}")
    if dropped_edges:
        for e in dropped_edges:
            print(f"    [DROPPED edge] {e.source_value!r} --[{e.type.value}]--> {e.target_value!r}")
    print()

    print("[OK] Bob API connectivity check passed.")
    print("=" * 60)


def _print_last_log_line(settings) -> None:
    """Print the last line of the real log file for debugging."""
    log_path = Path(getattr(settings, "BOB_LOG_PATH", "logs/bob_calls.jsonl"))
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            print(f"\nLast log entry ({log_path}):", file=sys.stderr)
            print(f"  {lines[-1]}", file=sys.stderr)
    else:
        print(f"\n(Log file not found: {log_path})", file=sys.stderr)


if __name__ == "__main__":
    main()
