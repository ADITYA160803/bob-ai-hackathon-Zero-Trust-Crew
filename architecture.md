# JAAL — Architecture

## 2.1 App Flow

```
[Upload text/CSV] → [Parser/Normalizer] → [Bob Extractor → JSON] → [Entity Resolver]
      → [Graph Builder (NetworkX)] → [Analytics: metrics + communities]
      → [Pattern Classifier] → [Hierarchy/Role Scorer]
      → [Bob Brief Writer + Template] → [UI Dashboard + PDF/MD export]
```

User journey: Upload → Processing (progress steps) → Dashboard (Graph | Hierarchy | Timeline | Suspects) → Case Brief → Export.

## 2.2 Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + TypeScript, Tailwind CSS | Fast, team-friendly |
| Graph viz | Cytoscape.js (react-cytoscapejs) | Good layouts (cose, dagre for hierarchy) |
| Charts | Recharts | Timeline / amounts |
| Backend | Python 3.11 + FastAPI + Pydantic | Typed schemas, quick |
| AI | Bob (LLM API) via bob_client.py; regex fallback | Extraction + brief text |
| Graph analysis | NetworkX (+ greedy_modularity_communities) | Centrality, communities |
| Storage | SQLite (cases) or in-memory + JSON files | No infra for hackathon |
| PDF | WeasyPrint or ReportLab | Brief export |
| Tests | pytest, Vitest | |

## 2.3 Folder Structure

```
jaal/
├── docs/
├── data/
│   ├── scenarios/
│   │   ├── s1_simswap_jamtara/ {raw_notes.txt, call_logs.csv, transactions.csv, expected.json}
│   │   ├── s2_mule_layering/
│   │   └── s3_vishing_kyc/
│   └── sample_analysis.json
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── api/ {routes_cases.py, routes_analysis.py, routes_report.py}
│   ├── schemas/ {entities.py, graph.py, analysis.py}
│   ├── services/ {bob_client.py, parser.py, extractor.py, resolver.py}
│   ├── analysis/ {graph_builder.py, metrics.py, communities.py, pattern_classifier.py, hierarchy.py}
│   ├── reports/ {brief_builder.py, pdf_export.py, templates/fir_brief.md.j2}
│   └── prompts/ {extract.md, pattern_confirm.md, brief.md}
├── frontend/
│   └── src/
│       ├── pages/ {Upload.tsx, Dashboard.tsx, Brief.tsx}
│       ├── components/ {GraphView.tsx, HierarchyView.tsx, Timeline.tsx, SuspectTable.tsx, PatternBadge.tsx, EntityPanel.tsx}
│       ├── api/client.ts
│       └── types/
├── tests/
├── .env.example
└── README.md
```

## 2.4 API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | /api/cases | Create case, upload files/text |
| POST | /api/cases/{id}/analyze | Run full pipeline |
| GET | /api/cases/{id}/graph | Nodes + edges |
| GET | /api/cases/{id}/analysis | Pattern, roles, scores, timeline |
| GET | /api/cases/{id}/brief?format=md\|pdf | FIR-ready brief |
| GET | /api/demo/{scenario} | Load a mock scenario instantly |

## 2.5 Core Data Schemas

### Node
```json
{
  "id": "PH_9876500001",
  "type": "PHONE",
  "label": "98765 00001",
  "attrs": {"imei": "...", "sim_swapped_on": "2023-03-02"},
  "sources": ["call_logs.csv#L14", "raw_notes.txt#p2"]
}
```
Node types: `PERSON`, `PHONE`, `DEVICE`, `BANK_ACCOUNT`, `UPI_ID`, `IP`, `LOCATION`

### Edge
```json
{
  "id": "E101",
  "source": "BA_1234",
  "target": "BA_5678",
  "type": "TRANSFERRED_TO",
  "attrs": {"amount": 45000, "ts": "2023-03-02T11:42:00"},
  "evidence": "transactions.csv#L22"
}
```
Edge types: `OWNS`, `USES_DEVICE`, `SIM_IN_DEVICE`, `CALLED`, `SMS_SENT`, `TRANSFERRED_TO`, `LOGGED_IN_FROM`

### AnalysisResult
```json
{
  "pattern": {
    "type": "SIM_SWAP",
    "secondary": ["MULE_LAYERING"],
    "confidence": 0.91,
    "reasons": ["SIM replaced 4x in 30 days", "Login from new device 2 min after SIM swap"]
  },
  "roles": [
    {"node_id": "PE_VIKRAM", "role": "KINGPIN", "score": 0.88, "why": ["terminal sink of 71% funds"]}
  ],
  "hierarchy": {
    "levels": [["PE_VIKRAM"], ["PE_H1", "PE_H2"], ["BA_M1", "BA_M2"], ["VICTIMS"]]
  },
  "totals": {"loss_inr": 1250000, "victims": 14, "mules": 6},
  "timeline": [{"ts": "2023-03-01T10:00:00", "event": "SIM swap initiated"}]
}
```

## 2.6 Analysis Logic (Role Scoring Rules)

- **Victim:** funds flow out once to unknown account; receives OTP call/SMS; no onward flow.
- **Operator:** high out-degree CALLED to many victims, shared devices, short calls.
- **Mule:** high fan-in + fast fan-out (pass-through ratio ~1, dwell time < 30 min).
- **Handler:** connects several mules/operators (high betweenness), receives partial cash-out.
- **Kingpin:** terminal sink of largest share of funds, few direct victim contacts, high betweenness, contacted by handlers.

Pattern rules:
- `SIM_SWAP` = SIM/IMEI change + OTP redirection + login from new device + rapid debit
- `MULE_LAYERING` = multi-hop chains, fan-in/fan-out
- `VISHING` = many victim inbound calls from few numbers + OTP shared
- `PHISHING_KYC` = links/SMS to many + shared IPs/devices
- `INVESTMENT_TASK` = small early payouts then large deposits
