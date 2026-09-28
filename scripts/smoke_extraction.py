"""
scripts/smoke_extraction.py

End-to-end sample check for the backend extraction pipeline.

Runs ~10 lines of made-up text through the full pipeline with
FORCE_FALLBACK=True (regex only — no Bob API key needed) and prints
the resolved graph as pretty-printed JSON.

Usage
─────
    JAAL_TESTING=1 python scripts/smoke_extraction.py

All data is MOCK.  No real names, phone numbers, accounts or IMEIs.
"""
from __future__ import annotations

import json
import os
import sys

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("JAAL_TESTING", "1")

# Force regex fallback so the script works offline with no API key
os.environ["FORCE_FALLBACK"] = "1"

# Reload settings after setting the env var
import importlib
import backend.config as _cfg
importlib.reload(_cfg)

from backend.services.pipeline import PipelineInput, run_extraction_pipeline

# ---------------------------------------------------------------------------
# Mock input — ~10 lines covering phones, IMEI, UPI, transfer with amount+ts
# ---------------------------------------------------------------------------

MOCK_TEXT = """\
2024-03-01 09:10 — Suspect A called 9876500001 from +919876500002.
2024-03-01 09:15 — Device IMEI 353456789012345 detected on network.
2024-03-01 09:20 — UPI transfer: 9876500001 sent ₹45,000 to account 001122334455.
2024-03-01 09:20 — UPI ID raj@okaxis confirmed as sender.
2024-03-01 09:25 — Account 001122334455 forwarded ₹40,000 to 556677889900.
2024-03-01 09:30 — Login from IP 203.0.113.42 using device 353456789012345.
2024-03-01 09:35 — SMS sent from 9876500002 to 8888800001 with OTP.
2024-03-01 09:40 — Suspect B (8888800001) called victim at 7777700001.
2024-03-01 09:45 — UPI ID suspect@paytm linked to account 556677889900.
2024-03-01 09:50 — Location: Jamtara district flagged in call records.
"""

MOCK_CSV = """\
txn_id,sender_phone,receiver_account,amount,timestamp
TXN001,9876500001,001122334455,45000,2024-03-01T09:20:00
TXN002,9876500001,556677889900,40000,2024-03-01T09:25:00
"""

# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    inputs = [
        PipelineInput(text=MOCK_TEXT),
        PipelineInput(filename="mock_transactions.csv", content=MOCK_CSV.encode()),
    ]

    print("=" * 60)
    print("JAAL — Smoke extraction (FORCE_FALLBACK=True, mock data)")
    print("=" * 60)

    result = run_extraction_pipeline(inputs)

    print(f"\nStats:")
    print(f"  Chunks      : {result.stats.chunks}")
    print(f"  Nodes       : {result.stats.nodes}")
    print(f"  Edges       : {result.stats.edges}")
    print(f"  Used fallback: {result.used_fallback}")

    print("\nResolved graph (JSON):")
    print(json.dumps(result.graph.model_dump(), indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("Node summary:")
    for node in result.graph.nodes:
        src = ", ".join(node.sources)
        print(f"  [{node.type.value:13s}] {node.id:30s}  sources: {src}")

    if result.graph.edges:
        print("\nEdge summary:")
        for edge in result.graph.edges:
            print(f"  {edge.id}: {edge.source} --[{edge.type.value}]--> {edge.target}  ({edge.evidence})")
    else:
        print("\n(No edges — regex fallback does not produce semantic edges)")

    print("\nSmoke check complete.")


if __name__ == "__main__":
    main()
