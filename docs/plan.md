# Build plan

Phase order, agreed with Gokul on 2026-10-15. Blocks refer to `features.md`; each phase is done only when that block's "Done when" criteria are met, tests pass and ruff is clean. Work inside a phase goes in small steps: tests first, implementation, ruff, local commit.

| Phase | Build | Blocks | Decision needed first |
|---|---|---|---|
| 0. Setup | uv workspace, ruff, pytest, `.env.example`, folder skeleton | part of A | none |
| 1. Foundation | Supabase schema (tenancy, api_keys, runs, steps, usage_daily), RLS, RLS isolation tests, API key create/hash/verify/revoke | A | none (dev cloud project chosen) |
| 2. Capture | SDK LangGraph callback + buffered async sender, `POST /v1/runs` (idempotent, enqueue to pgmq), usage counters | B | none (FastAPI on Vercel `bom1` chosen) |
| 3. Firewall core | Taint tracking, secret/PII redaction, "tainted runs never become active" rule | G (first half) | none |
| 4. Scoring | Scorer pipeline (tests/feedback/events, judge fallback), `POST /v1/feedback` | C | none (Claude Haiku 5.5 chosen) |
| 5. Distillation | Playbooks, failure signatures, dedupe/merge, versioning, provenance, embeddings | D | Embedding model |
| 6. Recall | Hybrid search, gate score, holdout, warnings, `POST /v1/recall`, SDK recall node | E | none |
| 7. Proof (MVP) | Benchmark harness: cold vs with memory, success rate and token deltas | F | none |
| 8. Firewall complete | Injection classifier, anomaly check, quarantine, review queue, poisoning suite in CI | G (second half) | none |
| 9. Regression | Eval case generation, `retrack test` CLI, GitHub Action | H | none |
| 10. Migration | Model-migration replay and per-playbook report | I | none |
| 11. Recovery | Known-fix recovery, circuit-breaker, plan replay | J | none |
| 12. Dashboard | API keys, ROI holdout charts, review/quarantine queues, playbook diff, migration reports; super-admin analytics across all projects, Gokul only | L | Dashboard login |
| 13. Fleet sharing | Cross-agent playbook proposals, approve, rollback | K | none |

Later (block M): TypeScript SDK, OpenTelemetry ingestion, self-hosting, audit logs.

## Status
- Phase 0: done.
- Phase 1: done (schema, RLS, API keys).
- Phase 2: done (capture SDK, `POST /v1/runs`, queue, deployed at `https://retrack-api.vercel.app` in `bom1`).
- Phase 3: done (redaction at ingest, taint tracking, promotion rule, workers via Supabase Cron → `/internal/drain`, verified live).

## Why this order
- **Firewall is split.** Redaction and the taint gate (Phase 3) come before anything is embedded or distilled, so secrets never reach vectors and rule 8 in `CLAUDE.md` holds from the first playbook. The LLM-heavy checks (Phase 8) land before any external user relies on recall.
- **Phase 7 is the MVP.** It proves the core claim (memory makes agents cheaper and more reliable) with numbers.
- **Dashboard is late.** Until Phase 12, API keys are managed with a small CLI script, which also defers the login decision.

## Database workflow
No ORM. Schema, RLS policies, pgmq queues and indexes live as plain SQL in `supabase/migrations/`, applied with the Supabase CLI, so nothing is set up by hand in the Supabase dashboard.
