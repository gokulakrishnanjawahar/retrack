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
rt.feedback(run_id, outcome="success", source="test")
```
Final shapes are decided during implementation; propose before changing.
