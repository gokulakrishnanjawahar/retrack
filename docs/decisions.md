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
| Phase order | See `plan.md` (2026-10-15) | Change only with Gokul's approval |
| Local development | Dev Supabase cloud project (no Docker); migrations applied with Supabase CLI `db push` | Tests that need a database run against it |
| Backend framework | FastAPI (Python) | Portable across hosts |
| Hosting | Vercel, region `bom1` (Mumbai), same region as the database | Hobby (free) while building; Pro required at launch (commercial use) |
| Worker trigger | Supabase Cron (`pg_cron` + `pg_net`) calls a secret-protected `/internal/drain` endpoint every minute | Free; defined in SQL migrations. GitHub Actions and Vercel Hobby cron rejected (too slow) |
| LLM (judge, distiller, firewall classifier) | Claude Haiku 5.5 (Anthropic), low effort by default; raise effort per job only if evals show it helps. All calls go through a provider-agnostic `LLMClient` interface | Decided 2026-10-19. Prompts stay under 100k tokens (cheaper price tier). Compared against Gemini 2.5 Flash-Lite, which is lower quality and being retired |
| LLM keys at launch | Customers can bring their own LLM key (encrypted, never logged); Retrack's own key is used for development and testing | Testing budget about $5 |
| ORM | None. Plain SQL migrations in `supabase/migrations/` via Supabase CLI | Python DB driver chosen when first needed |

## OPEN (ask before choosing)
| Area | Options under consideration | Blocks |
|---|---|---|
| Embedding model | To analyse (quality, cost, dimension, provider) | Vector dimension, Blocks D and E |
| Dashboard login | Supabase Auth, custom, or Clerk | Block L |
| Open vs closed source, licence | Decide after the product is built; repo stays private until then | Repo structure, licence file |
| Object storage for traces | Supabase Storage likely | Trace archive |
