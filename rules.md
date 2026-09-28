# JAAL — Rules

## 3.1 What to BUILD
- Only features F1-F9 in PRD.md until every one works end-to-end on all 3 mock scenarios.
- Every output claim must trace to evidence (sources on nodes/edges). No evidence → don't display it.
- Every screen must work with data/sample_analysis.json (offline demo mode). Demo must never depend on live internet.
- Brief must contain: header/disclaimer, case summary, complainant/victims, accused & roles, modus operandi, timeline, financial trail table, digital evidence table (phones/IMEI/accounts/IPs), suggested legal sections, recommended actions, annexures.

## 3.2 What to USE
- Stack in architecture.md. Python type hints + Pydantic models for all data crossing module boundaries.
- Bob for extraction/summaries with strict JSON output, temperature 0-0.2, schema in the prompt, JSON-repair + retry (max 2).
- Regex fallback for phones (`(\+91)?[6-9]\d{9}`), IMEI (15 digits), UPI (`\w+@\w+`), IFSC, account numbers.
- Normalize before matching: strip spaces/+91/dashes, lowercase UPI, mask display (XXXXXX1234).
- Prompts live in backend/prompts/*.md, not inline strings.
- Conventional commits (feat:, fix:, docs:), small PRs, one reviewer.
- Follow design.md tokens only. No random colors or fonts.
- Update memory.md after every session.

## 3.3 What to AVOID
- **No real personal data**, real phone numbers or real accounts anywhere (including screenshots).
- No hard-coding answers for demo scenarios inside logic. Only expected.json may hold answers (used by tests only).
- No LLM-invented facts: if Bob returns a field with no source text, drop it.
- No stating guilt. Use "suspected", "indicator", "appears". Keep AI-assistance disclaimer in every export.
- No legal sections presented as final. Label "suggested, to be verified by IO".
- No secrets in git (.env only; commit .env.example).
- No new frameworks/libraries mid-project without Raj's approval.
- No editing another member's folder without telling them.
- No over-polishing before the core pipeline works.
- No graphs with > 500 nodes rendered at once; cluster or filter.

## 3.4 Definition of Done (per task)
Code runs, has at least one test or sample check, matches schema, evidence-linked, memory.md updated, PR reviewed.

## 3.5 Bob Usage Rules
- Coding assistant: always give it the docs first. Ask for small units (one module at a time).
- In-app: send only the necessary text chunk (<= ~3k tokens), never whole datasets in one call.
- Log every prompt/response to logs/bob_calls.jsonl (mock data only) for debugging and the demo.

## 3.6 Brief Checklist (required sections)
- [ ] Header with case number, date, station
- [ ] AI-assistance disclaimer banner
- [ ] Case summary (2-3 sentences)
- [ ] Complainant / victims table
- [ ] Accused & roles table (with "suspected" qualifier)
- [ ] Modus operandi narrative
- [ ] Chronological timeline
- [ ] Financial trail table (txn_id, sender, receiver, amount, timestamp)
- [ ] Digital evidence table (phones, IMEIs, accounts, IPs, UPI IDs)
- [ ] Suggested legal sections (IT Act 66C/66D, BNS 318/61) — labeled "suggested, verify with IO"
- [ ] Recommended actions (prioritized)
- [ ] Annexures reference
