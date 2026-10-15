# Architecture

## Data flow

```
Customer agent (LangGraph + Retrack SDK)
   │  1. POST /v1/runs (async, after the run)
   ▼
Ingest API ──► pgmq queue ──► Firewall pipeline ──► Scorer pipeline ──► Distiller pipeline
                                                                              │
                                                                              ▼
                                                           Postgres + pgvector (Supabase)
                                                           runs, steps, playbooks, failure
                                                           signatures, provenance, eval cases
                                                                              │
Customer agent ◄── 2. POST /v1/recall (before each task) ◄── Recall API ◄─────┘

Regression runner (CLI + GitHub Action) reads eval cases, replays against current or target model.
Dashboard (Next.js) reads metrics, review queue, quarantine, playbook diffs.
Raw full traces ──► object storage (compressed), not Postgres.
```

## Components

| Component | Responsibility | Tech (decided / OPEN) |
|---|---|---|
| Python SDK | LangGraph callback handler for capture; pre-task recall node; optional LangGraph `BaseStore` adapter; local mode (SQLite + sqlite-vec) | Python 3.12, langgraph, httpx |
| Ingest API | Authenticated, idempotent ingestion (run ID is the idempotency key), schema validation, backpressure; replies 202 immediately | FastAPI on Vercel (`bom1`) |
| Job queue | Fan-out of firewall, scoring, distillation and embedding jobs; retries; dead-letter queue | pgmq (decided); drained by Vercel cron jobs |
| Firewall pipeline | Taint propagation, secret and PII scanning, injection classifier, tool-choice anomaly checks, quarantine | LangGraph; LLM OPEN |
| Scorer pipeline | Outcome from tests, feedback, business events, then judge model as fallback; attaches confidence | LangGraph; LLM OPEN |
| Distiller pipeline | Playbook and failure-signature extraction, dedupe/merge, versioning | LangGraph; LLM OPEN |
| Store | All structured data and vector index | Supabase Postgres + pgvector (decided) |
| Recall API | Hybrid search (vector + full-text + metadata filters), rerank, confidence gate | FastAPI on Vercel (`bom1`) |
| Regression runner | Replays eval cases; model-migration report | Python CLI + GitHub Action |
| Dashboard | ROI holdout charts, review and quarantine queues, playbook diff/rollback, API key management | Next.js; login OPEN |
| Trace archive | Compressed full traces, retention per project | Object storage (Supabase Storage likely; confirm) |

## Key design principles
1. **Never slow the customer's agent.** Capture is fire-and-forget with a local buffer; recall has a strict timeout and fails open (agent proceeds without memory).
2. **Async everything heavy.** Ingest only validates and enqueues; all LLM work runs in workers.
3. **Untrusted by default.** Write path assumes inputs may be hostile.
4. **Version-aware memory.** Every playbook records the model and tool versions it was validated on.
5. **Provider-agnostic models.** All LLM and embedding calls go through one internal interface so providers can be swapped and customers can bring their own keys later.
6. **SDK and server are separate.** They share only the HTTP API contract.

## Pipeline stages per run
1. Ingest: validate, store run + steps, enqueue.
2. Firewall: set `taint_level`, redact secrets/PII, run injection check; quarantine if needed.
3. Score: set `outcome`, `outcome_source`, `confidence`.
4. Embed task text.
5. Distil (only novel or high-value runs): create or update playbook / failure signature; record provenance.
6. Generate eval case from new playbook or failure.
7. Increment usage counters.
