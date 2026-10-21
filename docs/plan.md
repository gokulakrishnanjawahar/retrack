# Build plan

Phase order, agreed with Gokul on 2026-10-15. Blocks refer to `features.md`; each phase is done only when that block's "Done when" criteria are met, tests pass and ruff is clean. Work inside a phase goes in small steps: tests first, implementation, ruff, local commit.

| Phase | Build | Blocks | Decision needed first |
|---|---|---|---|
| 0. Setup | uv workspace, ruff, pytest, `.env.example`, folder skeleton | part of A | none |
| 1. Foundation | Supabase schema (tenancy, api_keys, runs, steps, usage_daily), RLS, RLS isolation tests, API key create/hash/verify/revoke | A | none (dev cloud project chosen) |
| 2. Capture | SDK LangGraph callback + buffered async sender, `POST /v1/runs` (idempotent, enqueue to pgmq), usage counters | B | none (FastAPI on Vercel `bom1` chosen) |
| 3. Firewall core | Taint tracking, secret/PII redaction, "tainted runs never become active" rule | G (first half) | none |
| 4. Scoring | Scorer pipeline (tests/feedback/events, judge fallback), `POST /v1/feedback` | C | none (Claude Haiku 5.5 chosen) |
| 5. Distillation | Playbooks, failure signatures, dedupe/merge, versioning, provenance, embeddings | D | none (gemini-embedding-001 on Vertex AI Mumbai chosen) |
| 6. Recall | Hybrid search, gate score, holdout, warnings, `POST /v1/recall`, SDK recall node | E | none |
| 7. Proof (MVP) | Benchmark harness: cold vs with memory, success rate and token deltas | F | none |
| 8. Firewall complete | Injection classifier, anomaly check, quarantine, review queue, poisoning suite in CI | G (second half) | none |
| 9. Regression | Eval case generation, `retrack test` CLI, GitHub Action | H | none |
| 10. Migration | Model-migration replay and per-playbook report | I | none |
| 11. Recovery | Known-fix recovery, circuit-breaker, plan replay | J | none |
| 12. Dashboard | API keys, ROI holdout charts, review/quarantine queues, playbook diff, migration reports; super-admin analytics across all projects, Gokul only | L | none (Supabase Auth chosen) |
| 13. Fleet sharing | Cross-agent playbook proposals, approve, rollback | K | none |

Later (block M): TypeScript SDK, OpenTelemetry ingestion, self-hosting, audit logs.

## Status
- Phase 0: done.
- Phase 1: done (schema, RLS, API keys).
- Phase 2: done (capture SDK, `POST /v1/runs`, queue, deployed at `https://retrack-api.vercel.app` in `bom1`).
- Phase 3: done (redaction at ingest, taint tracking, promotion rule, workers via Supabase Cron → `/internal/drain`, verified live).
- Phase 4: done (outcome signals, AI judge on Claude Haiku 5.5, `POST /v1/feedback`, SDK `rt.feedback`, final answers and tool results captured). Deployed with the LLM **off**; judge quality check 17/23 with no false successes ($0.0025 spent). Turning the live judge on needs Gokul's approval.
- Phase 5: built and tested with fake LLM and embedder (playbooks, failure signatures, provenance, review queue, promotion guard, embedding cache, `retrack_pipeline` role). Live Vertex AI setup pending Gokul's Google Cloud billing.
- Phase 6: built (`POST /v1/recall`, gate score, holdout, warnings, learning loop, SDK `rt.recall` / `recall_node`). Recall runs keyword-only until embeddings are enabled. Full suite passed (347); deploy pending.
- Phase 7: benchmark harness built (`uv run python -m benchmarks.run`). Fake mode ($0) shows the pipeline end to end: success 50% -> 100%, tool calls 3.0 -> 2.0, memory recalled on 20/20 tasks. Real mode (Claude Haiku 5.5 agent, about $0.07, hard cap) needs Google billing for embeddings and Gokul's approval.
- Phase 8: done locally (injection heuristics on every run, LLM classifier on the memory write path, tool-anomaly check, quarantine and review via `retrack-admin`, findings audit trail, poisoning suite of 105 cases). CI deferred. Full suite: 500 passed. Deploy pending.
- Phase 9: built (eval cases from memory via triggers, `GET /v1/eval-cases`, `POST /v1/eval-results`, `retrack test` command, customer GitHub Action template). AI-judged assertions deferred. Full suite: 519 passed.
- Phase 10: done (`retrack migrate`, migration reports, `POST /v1/migrations`, `GET /v1/migrations/{id}`, passing playbooks validated for the new model). Full suite: 531 passed.
- Hardening (between Phases 10 and 11): one-round-trip ingest (`private.ingest_run`), per-project ingest rate limit, daily retention job. Full suite: 538 passed.
- Deployed 2026-10-21: Phases 0-10 + hardening live at `https://retrack-api.vercel.app` (LLM and embeddings off). Measured live: ingest about 22 ms server median (was about 60 ms); recall 15 ms median / 26 ms p95 server-side in keyword mode; Cron processed 25/25 runs in 43 s.
- Phase 11: built (known-fix learning, automatic unrecoverable flag, recall warnings with fixes, plan replay eligibility and demotion, SDK `memory.protect` circuit breaker and `replay_of`).
- Phase 12: done (full suite: 598 passed; dashboard unit tests 16 passed). Built: Supabase Auth login, onboarding with live first-run wait, API keys, project settings, overview (KPIs, memory lift vs holdout, runs chart, live run feed over Realtime), runs explorer with step timeline, memory board, playbook detail with version diff, quarantine and retire, review queue, recall inspector, regression (cases, pass rate by test run, CI snippet) and model-migration reports, super-admin analytics at `/admin` (users, runs across projects, worker and queue health; 404 for everyone else). Migrations applied to dev. Audit afterwards added failure-signature detail with the circuit-breaker override, project usage, plan-replay readiness, and fixed number fields.
- Phase 13: done (full suite: 633 passed): fleet proposals (share a playbook with another agent as a new playbook or an update; active only after an owner or admin approves), rollback to any version with its embedding, `GET /v1/playbooks`, `GET /v1/playbooks/{id}/versions`, `PATCH /v1/playbooks/{id}` (quarantine and retire only), `GET /v1/metrics`. All spec'd API endpoints now exist. Audit afterwards fixed approval of stale proposals, superseded review items, revalidation after content changes, and request-size limits. All phases (0-13) are built; deploying Phases 11-13 and the dashboard is next.

## Why this order
- **Firewall is split.** Redaction and the taint gate (Phase 3) come before anything is embedded or distilled, so secrets never reach vectors and rule 8 in `CLAUDE.md` holds from the first playbook. The LLM-heavy checks (Phase 8) land before any external user relies on recall.
- **Phase 7 is the MVP.** It proves the core claim (memory makes agents cheaper and more reliable) with numbers.
- **Dashboard is late.** Until Phase 12, API keys are managed with a small CLI script, which also defers the login decision.

## Database workflow
No ORM. Schema, RLS policies, pgmq queues and indexes live as plain SQL in `supabase/migrations/`, applied with the Supabase CLI, so nothing is set up by hand in the Supabase dashboard.
