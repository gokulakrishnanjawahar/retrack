# Public API (v1)

Authentication: `Authorization: Bearer <api_key>` on every request. The key identifies the project. All responses are JSON. Errors use `{ "error": { "code": "...", "message": "..." } }`.

| Endpoint | Purpose |
|---|---|
| `POST /v1/runs` | Ingest a run with steps and optional outcome hints. Idempotent on run `id`. Returns `202 Accepted`; processing is async. |
| `POST /v1/recall` | Given task text and context (agent, model_id, tool_versions), return gated playbooks and failure warnings with scores. Strict latency budget. |
| `POST /v1/feedback` | Attach a late outcome signal (user rating, business event, test result) to a run. |
| `GET /v1/playbooks` | List playbooks with filters (agent, status). |
| `GET /v1/playbooks/{id}/versions` | Version history for diff. |
| `PATCH /v1/playbooks/{id}` | Quarantine or retire. Approve and roll back are dashboard-only (403 here). |
| `POST /v1/migrations` | Start a replay of eval cases against a target model; returns a report id. |
| `GET /v1/migrations/{id}` | Per-playbook pass/fail report. |
| `GET /v1/metrics` | Holdout-based success rate, token and cost deltas, recall hit rate, for a time range. |

## Internal routes
`POST /internal/drain`: worker entry point, called every minute by Supabase Cron. Requires header `X-Retrack-Worker-Secret` (env `RETRACK_WORKER_SECRET`, also in Supabase Vault); returns 503 when not configured and never accepts API keys. Response: `{"processed": n, "retrying": n, "dead_lettered": n, "scoring_gave_up": n}`. Firewall and scoring commit separately: if only scoring (the judge) keeps failing, the job completes with the run left `unknown` instead of being dead-lettered. The time budget is checked before every job.

## Playbook and metrics endpoints (Phase 13)
API keys can read memory and take it out of service, never put it into service (decided 2026-10-21): an agent's key could be leaked or steered by injected text, so approving and rolling back need a person in the dashboard.
- `GET /v1/playbooks?agent=NAME&status=active|candidate|quarantined|retired|all&limit=1-200`: `{"playbooks": [{"id", "agent", "status", "version", "title", "task_pattern", "preconditions", "steps", "pitfalls", "uses", "successes", "success_rate", "confidence", "validated_models", "tool_versions", "origin_playbook_id", "updated_at"}]}`, newest change first; `status` defaults to `active`, `limit` to 50.
- `GET /v1/playbooks/{id}/versions`: `{"playbook_id", "versions": [{"version", "snapshot", "change_reason", "created_at"}]}`, newest first; `404 playbook_not_found`.
- `PATCH /v1/playbooks/{id}`: `{"action": "quarantine" | "retire", "note"?: string (max 500)}` -> `200 {"id", "status"}`. Quarantine reopens review (`reason`: `quarantined by api key <prefix>: <note>`); retire closes open reviews and retires the regression case. `"approve"` and `"rollback"` -> `403 forbidden`. `404 playbook_not_found`.
- `GET /v1/metrics?days=7-90` (default 30): `{"days", "runs", "success_rate", "memory": {"runs", "known", "successes", "success_rate", "avg_tokens", "avg_cost_usd"}, "holdout": {same}, "lift_points", "token_change", "cost_change", "enough_evidence", "recalls": {"total", "holdout", "hit_rate", "p50_latency_ms", "p95_latency_ms"}}`. `memory` = runs that asked for memory and were not held out; `holdout` = runs held out; success rates use known outcomes only; `lift_points` = memory minus holdout success rate in percentage points; `token_change` / `cost_change` are relative (−0.2 = 20% less with memory); `enough_evidence` needs 20 holdout runs with a known outcome; `hit_rate` = non-holdout recalls that returned at least one playbook.

## Regression endpoints (Phase 9)
- `GET /v1/eval-cases?agent=NAME`: `{"cases": [{"id", "source" (playbook / failure), "input": {"task"}, "assertions": [...], "critical", "last_result"}]}`, active cases only.
- `POST /v1/eval-results`: `{"test_run_id", "model_id"?, "results": [{"case_id", "passed", "details"?}]}` (1-1000 results), optional `"migration_id"` -> `202 {"recorded": n}`; `404 not_found` if any case or the migration is not in the project.
- `POST /v1/migrations`: `{"agent", "to_model", "from_model"?, "model_applied"?}` -> `201 {"id", "status": "running"}`; `404 agent_not_found`.
- `GET /v1/migrations/{id}`: `{"id", "agent", "from_model", "to_model", "model_applied", "status", "summary": {"counts": {passes, needs_relearning, breaks, fixed, returns}, "items": [{"case_id", "source", "source_id", "title", "result", "failures"}]}, "created_at", "completed_at"}`.

## Run ingest request (approved 2026-10-17)
One run = one finished agent task, sent by the SDK after the run. Fields describe the **customer's** agent (its model, its tools), not Retrack.
```json
{
  "id": "uuid (client-generated; idempotency key)",
  "agent": "support-agent",
  "task": "Refund order #123 that arrived damaged",
  "model_id": "claude-haiku-5-5",
  "tool_versions": {"stripe": "2026-09", "orders_api": "v3"},
  "tokens_in": 1200, "tokens_out": 300, "cost_usd": 0.004, "latency_ms": 5400,
  "outcome_hint": {"outcome": "success", "source": "test"},
  "output": "Refunded order #123; the money reaches your card in 5-7 days.",
  "replay_of": "playbook uuid when the run followed a replay plan (optional)",
  "steps": [
    {"idx": 0, "type": "tool", "tool_name": "orders_api", "args": {"order_id": "123"},
     "result_class": "ok", "error_class": null, "latency_ms": 120, "input_trust": "untrusted"}
  ]
}
```
Limits: request body at most 1 MB (413), at most 500 steps (422). The server redacts secrets and personal data in `task`, `args` and `output` before storing them. `output` (optional, added 2026-10-19) is the agent's final answer: the SDK takes the last AI message, or a state field named with `rt.callback(output_key=...)`; it is truncated to 4,000 characters. The judge checks it against the steps, so a claimed success with a failed key step is a failure. Hand-offs to a human are judged `unknown`. `outcome_hint.source` is one of `test`, `feedback`, `event`.

Response `202`: `{"id": "...", "duplicate": false}`; `duplicate` is true when the run id was already stored for this project. `429 rate_limited` with a `Retry-After` header when the project exceeds its runs-per-minute limit.

## Feedback request (Phase 4)
`POST /v1/feedback` attaches a late outcome signal to a run of the key's project.
```json
{"run_id": "uuid", "outcome": "success", "source": "test", "detail": {"suite": "smoke"}}
```
`source` is `test` (confidence 1.0), `event` (0.9) or `feedback` (0.8); `judge` is reserved for Retrack. `detail` is redacted and stored. Response `202`: `{"run_id", "outcome", "outcome_source", "confidence"}` — the run's resolved outcome. `404 run_not_found` if the run is not in the project. Body at most 16 KB.

Resolution: the highest-ranked source wins (test > event > feedback > judge); within a source, the latest signal wins. The AI judge runs only when a run has no signal, at most once, with confidence capped at 0.7 (0.5 for untrusted runs).

## Recall request (Phase 6)
```json
{
  "agent": "support-agent",
  "task": "Refund order #123 that arrived damaged",
  "model_id": "claude-haiku-5-5",
  "tool_versions": {"stripe": "2026-09", "orders_api": "v3"},
  "max_playbooks": 3,
  "run_id": "uuid of the run that follows (optional; links recall to run)"
}
```
`max_playbooks` 1-10 (default 3). The task is redacted before use. Unknown agents get empty memory.

## Recall response
```json
{
  "recall_id": "uuid",
  "playbooks": [
    {"id": "...", "version": 4, "score": 0.83, "title": "...", "preconditions": "...", "steps": [{"action": "...", "tool": "..."}], "pitfalls": "..."}
  ],
  "warnings": [
    {"id": "...", "fingerprint": "...", "tool": "orders_api", "error_class": "TimeoutError", "occurrences": 7, "last_seen": "...", "message": "...", "recovery": null}
  ],
  "replay_eligible": false,
  "holdout": false,
  "mode": "hybrid"
}
```
Warnings also carry `recovery`, `recovery_steps` and `unrecoverable`; playbooks carry `replay_eligible`; `replay_plan` is set when plan replay is allowed (Phase 11). `mode` is `hybrid` (vectors + keywords), `keyword` (embeddings off or slower than 150 ms), `holdout` or `no_agent`. Only `active` playbooks are ever returned. Warnings are failure signatures seen at least twice for the agent's tools.
When `holdout` is true, return no memory and mark the run so metrics can compare.

## SDK surface (Python, sketch)
```python
from retrack import Retrack

rt = Retrack(api_key=os.environ["RETRACK_API_KEY"], agent="support-agent")
graph = builder.compile()
result = graph.invoke(inputs, config={"callbacks": [rt.callback()]})  # capture
memory = rt.recall(task, run_id=run_id)  # before task; 400 ms, fails open
prompt_text = memory.as_prompt()  # or builder.add_node(rt.recall_node())
handler = rt.callback()  # handler.last_run_id after a run
rt.feedback(handler.last_run_id, outcome="success", source="test")
```
Final shapes are decided during implementation; propose before changing.
