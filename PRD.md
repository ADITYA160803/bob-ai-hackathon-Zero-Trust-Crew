# JAAL — Product Requirements Document

## 1.1 Problem
Cyber fraud rings (e.g. Jamtara SIM-swap/UPI ring, 95,000+ cases in FY2023) span many bank accounts, SIMs, devices and people. Police trace these links manually over weeks; without network visualization most cases stall.

## 1.2 Goal
Turn unstructured fraud intelligence into: entities + relationships → network graph → fraud pattern → organizational hierarchy → FIR-ready case brief with recommended actions. Target: raw input to brief in under 60 seconds.

## 1.3 Target Users
| User | Need |
|---|---|
| Cyber cell investigator (SI / Inspector) | Quickly see who is connected to whom, and who to act on first |
| Cybercrime unit supervisor (DSP/SP) | Understand ring structure and scale for resource decisions |
| Bank nodal / fraud-risk officer | Identify mule accounts to freeze |
| Prosecutor / legal reviewer | Evidence-backed summary and applicable sections |

## 1.4 Scope (MVP — must build)
| # | Feature | Acceptance criteria |
|---|---|---|
| F1 | Multi-input ingestion | Accepts pasted text, .txt, .csv (transactions, call logs). Batch of mixed files supported |
| F2 | Entity extraction (Bob) | Extracts Person, Phone/SIM, IMEI/Device, Bank Account, UPI ID, IP, Location, Amount, Timestamp as strict JSON |
| F3 | Relationship extraction | Edges: OWNS, USES_DEVICE, SIM_IN_DEVICE, CALLED, TRANSFERRED_TO, SENT_SMS, SHARES_* with evidence ref |
| F4 | Entity resolution | Same phone/account in multiple records merged into one node; name variants flagged |
| F5 | Network graph | Interactive, zoom/pan, click for details, filter by type and role |
| F6 | Pattern identification | Classifies into SIM-Swap, Mule Layering, Vishing/OTP, Phishing-KYC, Fake Investment/Task Scam, with confidence + reasons |
| F7 | Hierarchy mapping | Assigns Kingpin / Handler / Mule / Operator / Victim with score and explanation |
| F8 | FIR-ready case brief | Facts, timeline, accused, modus operandi, loss amount, evidence table, suggested sections, recommended actions. Export PDF and Markdown |
| F9 | Recommended actions | Prioritized list: freeze accounts, block SIMs/IMEIs, notices to banks/telcos, arrest priority |

## 1.5 Nice-to-have (only if MVP done)
Timeline animation of money flow; multi-case cross-linking; Hindi brief; risk-score heatmap; CSV/GraphML export.

## 1.6 Non-goals
Real data ingestion, live bank/telco integration, real legal filing, facial/biometric analysis, production auth.

## 1.7 Success Metrics
- Entity extraction F1 >= 0.85 on our 3 mock scenarios
- Correct pattern on all 3 scenarios
- Kingpin identified in top-2 on all scenarios
- End-to-end run < 60s
- Brief contains all required sections

## 1.8 Ethics & Legal Notes
- Mock data only. Brief carries a banner: "AI-assisted analysis. Requires verification by the investigating officer."
- Legal sections are suggestions (e.g. IT Act 66C/66D; BNS cheating/conspiracy/organised crime), verified by a human.
- Roles are risk indicators, not conclusions of guilt.
