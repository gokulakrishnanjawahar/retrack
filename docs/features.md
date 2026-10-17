# Features

Build order is in `plan.md`. Features are grouped into blocks with dependencies so any order can be chosen safely. Each block lists acceptance criteria: a block is done only when all are met and tests pass.

## Block A: Foundation
Depends on: nothing.
- Monorepo scaffold, uv workspace, ruff, pytest, `.env.example`.
- Supabase schema: tenancy, api_keys, runs, steps, usage_daily (+ RLS).
- API key create/hash/verify/revoke.
**Done when:** migrations apply cleanly on a fresh database; RLS tests prove one project cannot read another's rows; key verification tests pass.

## Block B: Capture
Depends on: A.
- SDK LangGraph callback handler; async buffered sender.
- `POST /v1/runs` with idempotency; enqueue to pgmq.
- Usage counter increments.
**Done when:** a sample LangGraph agent's runs appear in the database with all steps; sending the same run twice creates one row; SDK never raises when the server is down.

## Block C: Scoring
Depends on: B.
- Scorer pipeline: tests/feedback/events, then judge fallback; confidence.
- `POST /v1/feedback`.
**Done when:** runs with programmatic signals are scored without an LLM call; judge fallback works; late feedback updates outcome.

## Block D: Distillation
Depends on: C.
- Distiller pipeline: playbooks, failure signatures, dedupe/merge, versioning, provenance.
- Embeddings (model OPEN).
**Done when:** repeated similar successes merge into one playbook with rising `uses`; failures produce fingerprints; every playbook has provenance.

## Block E: Recall
Depends on: D.
- Hybrid search, gate score, holdout, warnings; `POST /v1/recall`; SDK recall node.
**Done when:** recall meets latency targets on 10k playbooks; below-threshold matches are not returned; holdout runs get no memory; SDK fails open on timeout.

## Block F: Benchmark harness
Depends on: E.
- Repetitive task set(s), run cold vs with memory, report success rate and token deltas.
**Done when:** one command produces a reproducible comparison report.

## Block G: Firewall
Depends on: B (can be built alongside C to E).
- Taint tracking, secret/PII redaction, injection classifier, anomaly check, quarantine, review queue, poisoning test suite in CI.
**Done when:** every case in the poisoning suite is blocked from `active`; redaction tests pass; quarantined playbooks are never recalled.

## Block H: Regression runner
Depends on: D.
- Eval case generation, `retrack test` CLI, GitHub Action.
**Done when:** a playbook and a failure each generate an eval case; CLI reports pass/fail; Action fails a PR on regression.

## Block I: Model migration
Depends on: H.
- Migration replay and report; `validated_models` tagging.
**Done when:** replaying against a second model produces a per-playbook report.

## Block J: Recovery and plan replay
Depends on: E, H.
- Known-fix recovery, circuit-breaker, plan replay under strict rules.
**Done when:** a known failure triggers the recorded recovery; unrecoverable fingerprints stop retries; replay only fires when all replay conditions hold and demotes on failure.

## Block K: Fleet sharing and review
Depends on: D, G.
- Propose playbooks across agents as reviewable changes; approve, diff, rollback.
**Done when:** a playbook from one agent can be proposed to another and only becomes active after approval; rollback restores a prior version.

## Block L: Dashboard
Depends on: A (grows with every block). Login provider OPEN.
- API key management, metrics/ROI holdout charts, review and quarantine queues, playbook diff, migration reports.
- Super-admin area (Gokul only): analytics across all organizations and projects (usage, runs, recalls, success rates, costs). Customers can never reach it.
**Done when:** each backend feature that exists has its screen; super-admin pages reject every account except the super-admin.

## Block M: Later
- TypeScript SDK; OpenTelemetry ingestion for non-LangGraph frameworks; self-hosted deployment; audit logs.
