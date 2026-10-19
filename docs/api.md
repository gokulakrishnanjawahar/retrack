# Public API (v1)

Authentication: `Authorization: Bearer <api_key>` on every request. The key identifies the project. All responses are JSON. Errors use `{ "error": { "code": "...", "message": "..." } }`.

| Endpoint | Purpose |
|---|---|
| `POST /v1/runs` | Ingest a run with steps and optional outcome hints. Idempotent on run `id`. Returns `202 Accepted`; processing is async. |
| `POST /v1/recall` | Given task text and context (agent, model_id, tool_versions), return gated playbooks and failure warnings with scores. Strict latency budget. |
| `POST /v1/feedback` | Attach a late outcome signal (user rating, business event, test result) to a run. |
| `GET /v1/playbooks` | List playbooks with filters (agent, status). |
| `GET /v1/playbooks/{id}/versions` | Version history for diff. |
| `PATCH /v1/playbooks/{id}` | Approve, quarantine, retire, or roll back to a version. |
| `POST /v1/migrations` | Start a replay of eval cases against a target model; returns a report id. |
| `GET /v1/migrations/{id}` | Per-playbook pass/fail report. |
| `GET /v1/metrics` | Holdout-based success rate, token and cost deltas, recall hit rate, for a time range. |

## Internal routes
`POST /internal/drain`: worker entry point, called every minute by Supabase Cron. Requires header `X-Retrack-Worker-Secret` (env `RETRACK_WORKER_SECRET`, also in Supabase Vault); returns 503 when not configured and never accepts API keys. Response: `{"processed": n, "retrying": n, "dead_lettered": n}`.

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
  "steps": [
    {"idx": 0, "type": "tool", "tool_name": "orders_api", "args": {"order_id": "123"},
     "result_class": "ok", "error_class": null, "latency_ms": 120, "input_trust": "untrusted"}
  ]
}
```
Limits: request body at most 1 MB (413), at most 500 steps (422). The server redacts secrets and personal data in `task`, `args` and `output` before storing them. `output` (optional, added 2026-10-19) is the agent's final answer: the SDK takes the last AI message, or a state field named with `rt.callback(output_key=...)`; it is truncated to 4,000 characters. The judge checks it against the steps, so a claimed success with a failed key step is a failure. Hand-offs to a human are judged `unknown`. `outcome_hint.source` is one of `test`, `feedback`, `event`.

Response `202`: `{"id": "...", "duplicate": false}`; `duplicate` is true when the run id was already stored for this project.

## Feedback request (Phase 4)
`POST /v1/feedback` attaches a late outcome signal to a run of the key's project.
```json
{"run_id": "uuid", "outcome": "success", "source": "test", "detail": {"suite": "smoke"}}
```
`source` is `test` (confidence 1.0), `event` (0.9) or `feedback` (0.8); `judge` is reserved for Retrack. `detail` is redacted and stored. Response `202`: `{"run_id", "outcome", "outcome_source", "confidence"}` — the run's resolved outcome. `404 run_not_found` if the run is not in the project. Body at most 16 KB.

Resolution: the highest-ranked source wins (test > event > feedback > judge); within a source, the latest signal wins. The AI judge runs only when a run has no signal, at most once, with confidence capped at 0.7 (0.5 for untrusted runs).

## Recall request (sketch)
```json
{
  "agent": "support-agent",
  "task": "Refund order #123 that arrived damaged",
  "model_id": "claude-haiku-5-5",
  "tool_versions": {"stripe": "2026-09", "orders_api": "v3"},
  "max_playbooks": 3
}
```

## Recall response (sketch)
```json
{
  "playbooks": [
    {"id": "...", "version": 4, "score": 0.83, "preconditions": "...", "steps": [...], "pitfalls": "..."}
  ],
  "warnings": [
    {"fingerprint": "...", "message": "orders_api returns 429 above 5 req/s; back off", "recovery": "..."}
  ],
  "replay_eligible": false,
  "holdout": false
}
```
When `holdout` is true, return no memory and mark the run so metrics can compare.

## SDK surface (Python, sketch)
```python
from retrack import Retrack

rt = Retrack(api_key=os.environ["RETRACK_API_KEY"], agent="support-agent")
graph = builder.compile()
result = graph.invoke(inputs, config={"callbacks": [rt.callback()]})  # capture
memory = rt.recall(task=..., model_id=..., tool_versions=...)  # before task
handler = rt.callback()  # handler.last_run_id after a run
rt.feedback(handler.last_run_id, outcome="success", source="test")
```
Final shapes are decided during implementation; propose before changing.
