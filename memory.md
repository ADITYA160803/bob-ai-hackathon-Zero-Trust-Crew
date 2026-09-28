# JAAL — Memory (Progress Log)

*Update at the end of EVERY work session. Bob reads this first.*
Legend: [x] done, [~] in progress, [ ] not started.
Format: `YYYY-MM-DD | who | what | next`

## Current Focus
- **Phase:** 2 complete + Phase 5 (Raj's half) complete
- **File(s) being worked on now:** Aditya → backend/analysis/; Aksh → data/scenarios/ + backend/reports/; Priyanshi → frontend/src/
- **Blockers:** none on Raj's side. Aditya's analysis modules needed before /api/cases/{id}/analysis returns real data.

## Team
| Member | Role | Bob session focus |
|---|---|---|
| Raj | Backend + AI | backend/services/, backend/api/ |
| Aditya | Graph + Detection | backend/analysis/ |
| Priyanshi | Frontend + UX | frontend/src/ |
| Aksh | Data + Brief + QA | data/scenarios/, backend/reports/ |

## Status by Phase

### Phase 0: Setup
- [x] Docs committed to /docs
- [x] Folder structure created
- [x] Bob API key confirmed (Raj) — set FORCE_FALLBACK=1 in .env for offline use
- [x] .env.example created (Raj)
- [x] Schemas v1 frozen (Raj + Aditya)

### Phase 1: Data & Contracts (Aksh)
- [ ] data/scenarios/s1_simswap_jamtara/*
- [ ] data/scenarios/s2_mule_layering/*
- [ ] data/scenarios/s3_vishing_kyc/*
- [ ] expected.json answer keys
- [ ] data/sample_analysis.json ← CRITICAL: Priyanshi blocked until this exists

### Phase 2: Extraction (Raj)
- [x] backend/schemas/entities.py + graph.py (Node, Edge, RawNode, RawEdge, GraphPayload, ExtractionResult)
- [x] backend/services/parser.py
- [x] backend/services/bob_client.py
- [x] backend/prompts/extract.md
- [x] backend/services/extractor.py (+ regex fallback, FORCE_FALLBACK switch)
- [x] backend/services/resolver.py
- [x] backend/services/pipeline.py (parser → extractor → resolver chain, TODO hooks for Aditya/Aksh)

### Phase 3: Analytics (Aditya)
- [ ] backend/analysis/graph_builder.py
- [ ] backend/analysis/metrics.py
- [ ] backend/analysis/communities.py
- [ ] backend/analysis/pattern_classifier.py
- [ ] backend/analysis/hierarchy.py

### Phase 4: Frontend Core (Priyanshi)
- [ ] Vite + Tailwind + theme tokens
- [ ] Upload.tsx
- [ ] GraphView.tsx (cytoscape)
- [ ] PatternBadge.tsx, EntityPanel.tsx
- [ ] Dashboard.tsx shell

### Phase 5: Integration (Raj + all)
- [x] API routes wired — POST /api/cases, POST /api/cases/{id}/analyze, GET /api/cases/{id}/graph, GET /api/demo/{scenario}, GET /api/cases/{id}/analysis (501 stub)
- [ ] Processing progress screen (Priyanshi)
- [ ] HierarchyView.tsx, Timeline.tsx, SuspectTable.tsx (Priyanshi)
- [ ] End-to-end demo scenario run (all — needs Aksh's scenarios + Aditya's analysis)

### Phase 6: Brief & Export (Aksh)
- [ ] templates/fir_brief.md.j2
- [ ] prompts/brief.md
- [ ] brief_builder.py
- [ ] pdf_export.py
- [ ] Brief.tsx preview

### Phase 7: Test & Polish (All)
- [ ] Unit tests
- [ ] E2E test on 3 scenarios
- [ ] Failure handling (LLM down, bad file)
- [ ] README, demo video, pitch rehearsal

## Decisions Log
- Stack fixed per architecture.md. Change only with Raj's approval.
- Project name: JAAL (means "network/web" in Hindi — fitting for a fraud network analyzer)

## Known Issues / Notes
- Submission form open TODAY 28 Sept 12:00 PM – 7:00 PM only
- Demo must work fully offline using data/sample_analysis.json

## Session Log
- 2026-09-28 | all | docs created, Bob prompts ready, starting parallel build | Phase 1-4 simultaneously
- 2026-09-28 | Raj | Phase 2 complete + Phase 5 backend half: main.py, config.py, .env.example, requirements.txt, schemas (Node/Edge/RawNode/RawEdge/GraphPayload/ExtractionResult), bob_client.py (JSON repair + retry + logging), prompts/extract.md (full prompt + worked example), parser.py (text+CSV chunking), extractor.py (LLM + regex fallback + grounding check), resolver.py (dedup + stable IDs + name variants), pipeline.py (chained), routes_cases.py + routes_analysis.py wired into main.py, scripts/smoke_extraction.py; 170 tests passing | Aditya: wire analysis modules into pipeline TODOs; Aksh: add data/scenarios/* so /api/demo works; Priyanshi: frontend can now call all API endpoints
- 2026-09-28 | Raj | Fixed 4 issues: (1) Evidence line numbers — extractor.py now emits source_ref#L<n> or #L<n>-<m> for every node and edge in both LLM and regex paths; resolver merges refs with no duplicates; tests updated. (2) Test log isolation — added BOB_LOG_PATH to config.py; bob_client.py reads it at call time; tests/conftest.py autouse fixture redirects to tmp_path for every test; logs/bob_calls.jsonl emptied; sentinel test added. (3) .gitignore created — .env, logs/*.jsonl, __pycache__/, *.pyc, .pytest_cache/, node_modules/, dist/, .venv/, *.egg-info/, .DS_Store; logs/.gitkeep un-ignored; no tracked files need git rm --cached (fresh repo). (4) scripts/check_bob.py — standalone connectivity check with pre-flight guards (FORCE_FALLBACK, missing/placeholder key, example.com URL), prints raw JSON + RawNode/RawEdge validation + grounding report + last log line on failure; README.md created with "Running against the real Bob API" section; 175 tests passing, smoke script clean | Next: Aditya wire analysis modules; Aksh add data/scenarios/*; Priyanshi start frontend
