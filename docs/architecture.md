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

## Runtime (where things run)

```
Customer agent + SDK
   │ HTTPS (Bearer API key)
   ▼
Vercel, region bom1 (Mumbai) ── one FastAPI app ─────────────────────────────┐
   │  /v1/*            public API: validate, store, enqueue, reply 202        │
   │  /internal/drain  worker entry: read jobs from pgmq, run pipelines       │
   ▼                                  ▲                                       │
Supabase, region ap-south-1 (Mumbai)  │ every minute, HTTP POST with secret   │
   Postgres + pgvector + pgmq ── Supabase Cron (pg_cron + pg_net) ────────────┘
```

- **API and workers are one FastAPI app on Vercel.** Public routes live under `/v1/`; worker routes live under `/internal/` and require a shared secret header. They never accept an API key.
- **Supabase Cron triggers workers.** A `pg_cron` job calls `/internal/drain` via `pg_net` every minute. The secret is kept in Supabase Vault. Both are defined in SQL migrations, so nothing is configured by hand.
- **Draining.** Each call reads a batch from pgmq with a visibility timeout, processes it, and deletes finished jobs. A job that fails becomes visible again and is retried; after a set number of attempts it moves to a dead-letter queue. Overlapping drain calls are safe because a read job is invisible to other readers. Each call stops well before Vercel's function time limit.
- **Embeddings.** gemini-embedding-001 via Vertex AI in `asia-south1`, called only when `RETRACK_EMBEDDINGS_ENABLED=true` and `GOOGLE_CLOUD_PROJECT` are set; cached per project by content hash.
- **Retrack's LLM.** Claude Haiku 5.5 is called only when `RETRACK_LLM_ENABLED=true` and `ANTHROPIC_API_KEY` are both set; otherwise the judge is skipped and runs stay `unknown` until a hard signal arrives. Tests use `FakeLLM` and never see the key.
- **Database connections.** Vercel functions connect through Supabase's transaction pooler, as the restricted `retrack_server` login. Each server instance keeps a small `psycopg-pool` connection pool (1–5 connections, checked on checkout) so requests skip connection setup. All tenant queries use transaction-local settings (`project_scope`), which work with transaction pooling.
- **Deploying.** Vercel project `retrack-api` (root directory `server/`, framework preset FastAPI; region `bom1` set in the repo-root `vercel.json`, because the CLI reads config from the folder you deploy from; production URL `https://retrack-api.vercel.app`). Vercel installs the *repo root's* dependencies from the workspace `uv.lock`, so the root `pyproject.toml` depends on `retrack-server`; `server/main.py` puts `server/src` on the import path because the package itself is not installed. `.vercelignore` keeps `.env`, tests and docs out of uploads.
- **One database for dev and the live deploy (for now).** The live worker (Supabase Cron -> Vercel) drains the same queue the dev tools use, so local experiments pause the Cron job while they run (the benchmark does this automatically). Before real customers, the live deploy needs its own Supabase project.
- **Same region.** API, workers and database all run in Mumbai, to meet the ingest (50 ms) and recall (300 ms) targets.

### Cost
| Stage | Supabase | Vercel | Notes |
|---|---|---|---|
| Building | Free | Hobby (free) | Free Supabase projects pause when inactive; Hobby is non-commercial only |
| Launch (paying customers) | Pro (~$25/mo) | Pro (~$20/mo) | Required for commercial use and no pausing |

LLM calls (from Phase 4) use Claude Haiku 5.5 (about $0.0004 per judge call); customers may bring their own key at launch. Embeddings use gemini-embedding-001 on Vertex AI in Mumbai (about $0.15 per 1M tokens).

## Components

| Component | Responsibility | Tech (decided / OPEN) |
|---|---|---|
| Python SDK | LangGraph callback handler for capture; pre-task recall node; optional LangGraph `BaseStore` adapter; local mode (SQLite + sqlite-vec) | Python 3.12, langgraph, httpx |
| Ingest API | Authenticated, idempotent ingestion (run ID is the idempotency key), schema validation, backpressure; replies 202 immediately | FastAPI on Vercel (`bom1`) |
| Job queue | Fan-out of firewall, scoring, distillation and embedding jobs; retries; dead-letter queue | pgmq (decided); drained by `/internal/drain`, triggered every minute by Supabase Cron |
| Firewall pipeline | Taint propagation, secret and PII scanning, injection classifier, tool-choice anomaly checks, quarantine | LangGraph; Claude Haiku 5.5 via `LLMClient` |
| Scorer pipeline | Outcome from tests, feedback, business events, then judge model as fallback; attaches confidence | LangGraph; Claude Haiku 5.5 via `LLMClient` |
| Distiller pipeline | Playbook and failure-signature extraction, dedupe/merge, versioning | LangGraph; Claude Haiku 5.5 via `LLMClient` |
| Store | All structured data and vector index | Supabase Postgres + pgvector (decided) |
| Recall API | Hybrid search (vector + full-text + metadata filters), rerank, confidence gate | FastAPI on Vercel (`bom1`) |
| Regression runner | Replays eval cases; model-migration report | Python CLI + GitHub Action |
| Dashboard | ROI holdout charts, live run feed, review and quarantine queues, fleet proposals, playbook diff and rollback, API key management, super-admin analytics | Next.js 16 on Vercel at `retrackai.vercel.app` (project `retrack-dashboard`, `bom1`); Supabase Auth; reads under RLS, writes through `dashboard_*` functions |
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
