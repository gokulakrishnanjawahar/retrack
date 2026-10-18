# Engineering constraints

## Service targets
| Metric | Target |
|---|---|
| Recall latency | p50 under 120 ms, p95 under 300 ms (server side) |
| SDK recall timeout | default 400 ms, then fail open (empty memory) |
| Ingest acknowledgement | under 50 ms p95 (validate + enqueue only) |
| Run to playbook availability | under 15 minutes normally; non-urgent batch work may take up to 24 h |
| Hosted availability | 99.5%+ |

## Cost rules (model spend is the main running cost)
1. **Distil only novel runs.** Skip distillation when a near-duplicate active playbook already covers the run; just update its stats.
2. **Prefer programmatic outcome signals** (tests, feedback, business events) over a judge model. Use the judge only as a fallback.
3. **Batch non-urgent LLM work** (distillation, judging) through the provider's batch API where available. *Deferred (decided 2026-10-19):* calls are made directly for now because test volumes are tiny; switch to the batch API once volume makes the 50% saving worthwhile.
4. **Keep prompts well under 100k tokens.** Truncate or summarise traces before sending to an LLM; some cheap models charge several times more above 100k tokens.
5. **Store raw traces in object storage**, not Postgres. Postgres holds structured fields only.
6. **Cache embeddings** by content hash; never re-embed unchanged text.
7. **Provider-agnostic interface** for all LLM and embedding calls, so cheaper models or customer-supplied keys can be used later.

## SDK rules
- Capture must never raise into the customer's code; log and drop on failure.
- Buffer and send asynchronously; bounded memory; flush on shutdown.
- No heavy dependencies; keep install small.
- Redact obvious secrets client-side before sending.

## Data rules
- Tenant isolation via RLS on every customer table.
- Per-project retention; deleting a project removes rows, vectors and archived traces (supports GDPR and India DPDP requests).
- Secrets and PII redacted before embedding.
