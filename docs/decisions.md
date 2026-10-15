# Decisions log

Update this file whenever a decision is made. Claude Code: never resolve an OPEN item yourself; ask Gokul.

## Decided
| Area | Decision | Notes |
|---|---|---|
| Name | Retrack | |
| Database | Supabase Postgres | |
| Vector store | pgvector inside Supabase Postgres | |
| Job queue | pgmq (Supabase Queues) | No extra service |
| Usage metering | Daily counters per project in Postgres (`usage_daily`) | Easy to change later; raw runs allow rebuilding history |
| SDK languages | Python first, TypeScript later | |
| Dashboard framework | Next.js | |
| SDK authentication | Per-project API keys, stored hashed, revocable | |
| Repo | Monorepo; may restructure for open source later | Keep `sdk/` independent of `server/` |
| Python tooling | uv, pytest, ruff | |
| Developer OS | macOS (Apple Silicon) | |
| Git | GitHub remote: gokulakrishnanjawahar/retrack, branch `main`; private while building | Open vs closed source decided after the product is built |
| Pricing | Not decided; out of scope for code | Only record usage |

## OPEN (ask before choosing)
| Area | Options under consideration | Blocks |
|---|---|---|
| Backend framework and hosting | To explore (e.g. FastAPI on Railway, Supabase Edge Functions, AWS, others) | Ingest API, Recall API, workers |
| Embedding model | To analyse (quality, cost, dimension, provider) | Vector dimension, Blocks D and E |
| LLM for distillation, judging, firewall | Proposed default Claude Haiku 5.5 behind a provider-agnostic interface; not confirmed | Blocks C, D, G |
| Dashboard login | Supabase Auth, custom, or Clerk | Block L |
| Local development setup | Supabase CLI local stack, plain Postgres in Docker, or a dev Supabase cloud project | First run of Block A |
| Phase order | Decided during the build; see `features.md` dependencies | Which block next |
| Open vs closed source, licence | Decide after the product is built; repo stays private until then | Repo structure, licence file |
| Object storage for traces | Supabase Storage likely | Trace archive |
