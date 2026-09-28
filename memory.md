# JAAL — Memory (Progress Log)

*Update at the end of EVERY work session. Bob reads this first.*
Legend: [x] done, [~] in progress, [ ] not started.
Format: `YYYY-MM-DD | who | what | next`

## Current Focus
- **Phase:** INTEGRATION COMPLETE — branch: integration
- **File(s) being worked on now:** All stages complete. Pending: submission.
- **Blockers:** None. All 7 stages executed. 466 tests passing (446 original + 20 e2e).

## Team
| Member | Role | Status |
|---|---|---|
| Raj | Backend + AI | ✅ Complete |
| Aditya | Graph + Detection | ✅ Merged (analysis/ modules all in IBM) |
| Priyanshi | Frontend + UX | ✅ Merged + extended (HierarchyView, Timeline, SuspectTable, Brief) |
| Aksh | Data + Brief + QA | ✅ Merged (s1, s2, s3 scenarios; brief template; e2e tests) |

## Status by Stage (integration branch)

### Stage 1: Merge Backend ✅
- [x] backend/analysis/ — graph_builder, metrics, communities, hierarchy, pattern_classifier, pipeline
- [x] backend/schemas/analysis.py, result.py, entities.py (ResolvedGraph), graph.py (to_resolved)
- [x] backend/services/resolver.py — full IBM impl (NOT Hackathon stub)
- [x] Contract test: 32/32 pass
- [x] networkx==3.4.2 in requirements.txt

### Stage 2: Wire Pipeline ✅
- [x] GET /api/demo — list available scenarios (ADDED — was missing)
- [x] GET /api/demo/{scenario} — run full pipeline
- [x] GET /api/demo/{scenario}/analysis — offline sample analysis
- [x] POST /api/cases/{id}/analyze → run_pipeline → AnalysisResult
- [x] GET /api/cases/{id}/analysis — real implementation

### Stage 3: Structured Extractor ✅
- [x] backend/services/structured_extractor.py — transactions.csv + call_logs.csv extraction
- [x] jinja2==3.1.6 added to requirements.txt
- [x] markdown==3.7 added to requirements.txt

### Stage 4: Reports ✅
- [x] backend/reports/brief_builder.py — Jinja2 + plain fallback
- [x] backend/reports/pdf_export.py — WeasyPrint + HTML fallback
- [x] backend/reports/templates/fir_brief.md.j2 — 11 sections per rules.md §3.6
- [x] GET /api/cases/{id}/brief?format=md|pdf|html

### Stage 5: Frontend ✅
- [x] Upload.tsx — file upload + demo scenario picker
- [x] Dashboard.tsx — 5-tab layout (Graph, Hierarchy, Timeline, Suspects, Brief)
- [x] GraphView.tsx — Cytoscape force-directed graph
- [x] HierarchyView.tsx ← NEW standalone component
- [x] Timeline.tsx ← NEW standalone component
- [x] SuspectTable.tsx ← NEW sortable table component
- [x] Brief.tsx ← NEW page with MD/PDF download
- [x] PatternBadge.tsx, EntityPanel.tsx — existing
- [x] npm run build — zero TypeScript errors ✅

### Stage 6: One-command run ✅
- [x] run.bat — Windows one-command startup
- [x] run.sh — Linux/macOS startup
- [x] Makefile — make dev, make test, make build, make install
- [x] README.md — updated with "One-command run" section

### Stage 7: E2E Tests + Memory ✅
- [x] tests/test_e2e.py — 20 e2e tests across s1, s2, s3, sample, health
- [x] data/scenarios/s3_vishing_kyc/ — mock scenario created (raw_notes, csv, expected.json)
- [x] Match/mismatch table prints vs expected.json on test run
- [x] memory.md — this update

## Decisions Log
- Stack fixed per architecture.md.
- IBM's resolver.py kept (Hackathon's was a stub — IBM has full dedup/normalisation)
- FORCE_FALLBACK=1 used for all offline tests — Bob not required for demo
- WeasyPrint optional — falls back to HTML on Windows (no GTK)
- KINGPIN role requires person-level financial flow (not available in regex-only mode)
- Project name: JAAL (means "network/web" in Hindi)

## Known Issues / Notes
- Submission form open TODAY 28 Sept 12:00 PM – 7:00 PM only
- Demo works fully offline using data/sample_analysis.json (FORCE_FALLBACK=1)
- s3_vishing_kyc is mock data (vishing/KYC fraud, 6 victims, ₹3.05L)
- WeasyPrint PDF falls back to HTML on Windows (no system GTK)

## Session Log
- 2026-09-28 | all | docs created, Bob prompts ready, starting parallel build | Phase 1-4 simultaneously
- 2026-09-28 | Raj | Phase 2 complete + Phase 5 backend half wired; routes, schemas, resolver, pipeline, extractor all done. 175 tests passing.
- 2026-09-28 | Integration | ALL 7 STAGES COMPLETE on branch 'integration'. git committed after each stage. 466 tests passing. Frontend builds clean (tsc + vite). All screens functional: Upload → Graph → Hierarchy → Timeline → Suspects → Brief → Export. Three scenarios (s1, s2, s3). One-command run: run.bat / run.sh / make dev.
