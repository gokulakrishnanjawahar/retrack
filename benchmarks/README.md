# benchmarks

`support_desk/`: does Retrack's memory make an agent better at repeated tasks?

```
set -a && . ./.env && set +a
uv run python -m benchmarks.run                        # fake mode: scripted agent, $0
uv run python -m benchmarks.run --mode real --approved-spend --budget-usd 0.10
```

A simulated support desk (orders, refunds, address changes) has gotchas a naive agent
hits. A learning round runs tasks without memory; Retrack captures, scores (test
signals), distils and auto-promotes playbooks. An evaluation round runs each new task
twice with the same world seed, without and with recalled memory. Reports go to
`results/` as Markdown and JSON, with bootstrap 95% intervals.

The harness pauses the live Supabase Cron worker while it runs (it shares the dev
queue) and always re-enables it. Real mode spends credits: Claude Haiku 5.5 as the agent
and distiller, Vertex AI embeddings; it needs explicit approval and a hard budget cap.

Real mode signs in to Google without a key, using a fresh Vercel development token
(valid about 12 hours; Vercel is reachable only on the hotspot from Gokul's usual networks):

```
vercel env pull .env.local
set -a && . ./.env && . ./.env.local && set +a
```
