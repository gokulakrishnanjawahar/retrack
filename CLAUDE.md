# Retrack

Retrack is a developer SaaS that gives production AI agents **experience memory**. It captures every agent run, verifies whether it succeeded, turns successes into reusable **playbooks** and failures into **failure signatures**, and recalls the right ones before the agent's next task. The same store doubles as a regression test suite and a model-migration safety net, and a memory firewall stops poisoned or untrusted runs from becoming memory.

Owner: Gokul (solo developer). Building the full product phase by phase.

## Read before working

This file is short on purpose. Before any feature work, read the relevant file in `docs/`:

| Working on | Read |
|---|---|
| Anything, first session | `docs/product.md`, `docs/decisions.md` |
| System design, new components | `docs/architecture.md` |
| Database, migrations | `docs/data-model.md` |
| HTTP endpoints, SDK calls | `docs/api.md` |
| Recall, ranking, plan replay | `docs/recall-gating.md` |
| Taint, redaction, quarantine | `docs/firewall.md` |
| Regression tests, model migration | `docs/regression-migration.md` |
| Cost, latency, limits | `docs/constraints.md` |
| What to build and in what order | `docs/plan.md`, `docs/features.md` |
| Words you don't recognise | `docs/glossary.md` |

## Decided stack

- **Database:** Supabase Postgres. **Vectors:** pgvector in the same database.
- **Job queue:** pgmq (Supabase Queues) in the same database.
- **SDK:** Python first (TypeScript later). Integrates with LangGraph.
- **Internal pipelines** (firewall, scorer, distiller): LangGraph.
- **Dashboard:** Next.js, login with Supabase Auth.
- **SDK auth:** per-project API keys, stored hashed.
- **Usage metering:** simple daily counters in Postgres.
- **Backend:** FastAPI, hosted on Vercel in `bom1` (Mumbai). Queue workers are triggered every minute by Supabase Cron calling `/internal/drain`.
- **LLM:** Claude Haiku 5.5 behind a provider-agnostic `LLMClient`; customers may bring their own key at launch.
- **Embeddings:** `gemini-embedding-001` on Vertex AI `asia-south1`, 1,536 dimensions, behind an `Embedder` interface.
- **Local development:** a dev Supabase cloud project (no Docker).
- **Migrations:** plain SQL in `supabase/migrations/`, applied with the Supabase CLI. No ORM.
- **Python tooling:** uv (packages, Python version), pytest, ruff.
- **Repo:** monorepo (layout below).
- **Developer machine:** macOS (Apple Silicon). Give macOS commands.

## OPEN decisions: ask Gokul before choosing

Do not pick any of these yourself. If a task depends on one, stop and ask. Full list and context in `docs/decisions.md`.

- Open source vs closed source, and licence

When an open decision blocks you, write code behind an interface (e.g. an `Embedder` or `LLMClient` protocol) only if Gokul agrees.

## Repo layout

```
retrack/
├── CLAUDE.md
├── docs/            # product and technical spec (source of truth)
├── sdk/             # Python SDK package (retrack), LangGraph integration
├── server/          # backend: ingest, recall, workers, pipelines
├── dashboard/       # Next.js app
├── supabase/        # SQL migrations
└── benchmarks/      # benchmark harness and task sets
```

Keep `sdk/` independent of `server/` (no imports across them; they talk only over the HTTP API). This keeps the open-source option available later.

## Working rules

1. **Plan first.** For any non-trivial task, read the relevant docs, propose a short plan, and wait for approval before writing code.
2. **Tests first.** Write or update pytest tests before the implementation. A task is done only when tests pass and ruff is clean.
3. **Ask before:** adding a dependency, changing the database schema, changing a public API shape, or touching an OPEN decision.
4. **Never commit secrets.** Keys go in `.env` (git-ignored); keep `.env.example` updated with variable names only.
5. **Small steps.** Commit after each working step with a clear message. Remote: `origin` (GitHub, `gokulakrishnanjawahar/retrack`), branch `main`. Push only when Gokul asks.
6. **Spec is the source of truth.** If code and `docs/` disagree, or the spec is unclear, ask. If a decision is made during work, update the relevant doc in the same change.
7. **Tenant isolation always.** Every query on customer data is scoped by `project_id` and protected by row-level security.
8. **Untrusted by default.** Nothing from a tainted run reaches active memory without passing the firewall or human review.

## Commands (Python)

```
uv sync                 # install dependencies
uv run pytest           # run tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

## Commands (database)

Dev project `retrack-dev` (ref in `.env`), org `retrack`, region ap-south-1. Load `.env` first: `set -a && . ./.env && set +a`.

```
supabase migration new <name>          # new SQL migration file
supabase db push --yes                 # apply migrations to the dev project
supabase db lint --linked -s public,private
psql "$DATABASE_URL"                   # SQL shell (session pooler)
```

Database tests read `DATABASE_URL` from `.env` and roll back every change; they are skipped without it.

Run the API locally (reads `.env` for `SERVER_DATABASE_URL` and `RETRACK_KEY_PEPPER`):

```
set -a && . ./.env && set +a && uv run uvicorn retrack_server.app:app --reload
```

## Commands (dashboard)

```
cd dashboard
npm run dev             # http://localhost:3000 (reads dashboard/.env.local)
npm test                # vitest
npm run lint && npx tsc --noEmit
```

`dashboard/.env.local` holds the Supabase URL and publishable key, `RETRACK_KEY_PEPPER` (same as the server's) and `NEXT_PUBLIC_RETRACK_API_URL`; names are in `dashboard/.env.example`.
