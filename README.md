# JAAL — Fraud Network Analyser

> **"Jaal"** (जाल) means *network* or *web* in Hindi — fitting for a fraud network analyser.

JAAL turns unstructured fraud intelligence (pasted text, call logs, transaction CSVs) into
an interactive entity–relationship graph, pattern classifications, role assignments, and an
FIR-ready case brief — in under 60 seconds.

---

## Quick start (offline / demo mode)

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (offline mode — no API key needed)
cp .env.example .env
# Edit .env and set FORCE_FALLBACK=1

# 4. Start the backend
uvicorn backend.main:app --reload

# 5. Run the extraction smoke test (no API key required)
JAAL_TESTING=1 python scripts/smoke_extraction.py
```

---

## Running tests

```bash
JAAL_TESTING=1 python -m pytest tests/ -v
```

All tests are fully mocked — no Bob API key required. The autouse fixture in
`tests/conftest.py` redirects log output to temporary directories so
`logs/bob_calls.jsonl` is never modified by the test suite.

---

## Running against the real Bob API

Use `scripts/check_bob.py` to verify your API credentials and confirm that Bob
can extract entities from a small mock chunk.

### Steps

1. **Copy the example env file and fill in your credentials:**

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set:

   ```
   BOB_API_KEY=<your real key>
   BOB_API_URL=<real endpoint, e.g. https://api.bob.example.ibm.com/v1/chat/completions>
   MODEL_NAME=<model name, e.g. bob-large>
   FORCE_FALLBACK=0
   ```

2. **Run the connectivity check:**

   ```bash
   python scripts/check_bob.py
   ```

   The script will:
   - Refuse to run if `FORCE_FALLBACK=1`, the key is missing/placeholder, or
     the URL still contains `example.com`, and print a clear message telling you
     what to fix.
   - Send one small mock chunk through `bob_client.call_json`.
   - Print the raw parsed JSON, validation results against `RawNode`/`RawEdge`,
     node/edge counts, and which values (if any) the grounding check would drop.
   - On failure, print the exact error and the last line of `logs/bob_calls.jsonl`
     so you can inspect the raw API response.

3. **Expected successful output:**

   ```
   ============================================================
   JAAL — Real Bob API connectivity check
   ============================================================
     URL   : https://…
     Model : bob-large
     Key   : sk-abc*****

   Sending mock chunk (… chars) …
     source_ref: check_bob#L1

   Raw parsed JSON:
   { … }

   Nodes : N returned  |  N valid  |  0 invalid
   Edges : N returned  |  N valid  |  0 invalid

   Grounding check:
     Nodes kept   : N  |  dropped (invented): 0
     Edges kept   : N  |  dropped (invented): 0

   [OK] Bob API connectivity check passed.
   ============================================================
   ```

> **Note:** `scripts/check_bob.py` is a manual diagnostic tool and is **not** part
> of the pytest suite. All `pytest` tests remain fully mocked regardless of your
> `.env` settings.

---

## Project structure

```
jaal/
├── backend/
│   ├── config.py              # Settings (BOB_API_KEY, BOB_LOG_PATH, …)
│   ├── services/
│   │   ├── bob_client.py      # LLM API wrapper + JSON repair + logging
│   │   ├── extractor.py       # LLM + regex fallback extraction
│   │   ├── resolver.py        # Entity dedup + stable IDs
│   │   ├── parser.py          # Text/CSV → Chunks with line numbers
│   │   └── pipeline.py        # Chained parser → extractor → resolver
│   ├── schemas/               # Pydantic models (Node, Edge, RawNode, …)
│   ├── api/                   # FastAPI routes
│   └── prompts/               # LLM prompt templates
├── tests/                     # pytest suite (fully mocked)
│   └── conftest.py            # Autouse fixture: redirects log to tmp_path
├── scripts/
│   ├── smoke_extraction.py    # Offline pipeline smoke test
│   └── check_bob.py           # Real Bob API connectivity check
├── logs/
│   ├── .gitkeep               # Keeps the logs/ directory in git
│   └── bob_calls.jsonl        # Runtime log (ignored by git; empty after tests)
├── .env.example               # Copy to .env and fill in credentials
└── README.md
```

---

## Evidence references

Every extracted entity and relationship carries an evidence reference in the form
`<filename>#L<start>-<end>` (or `#L<n>` for a single line), e.g.
`call_logs.csv#L14-38`. This allows every claim in the graph to be traced back
to an exact line in the source file.

---

## AI-assistance disclaimer

All analysis is AI-assisted and requires verification by the investigating officer.
Legal section suggestions are labelled *"suggested, to be verified with IO"* and
are not final legal opinions.
