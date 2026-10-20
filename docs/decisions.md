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
| Embedding model | `gemini-embedding-001` on Google Vertex AI, region `asia-south1` (Mumbai), 1,536 dimensions, behind an `Embedder` interface | Decided 2026-10-19. Top MTEB score among API models; 38 ms network from India vs 200-320 ms for Voyage, OpenAI, Gemini global and others (measured); paid Vertex does not train on data and processing stays in India. Upgrade to Gemini Embedding 2 when it is offered in Mumbai (re-embed; model recorded per vector). Vercel authenticates to Google keylessly via OIDC |
| LLM keys at launch | Customers can bring their own LLM key (encrypted, never logged); Retrack's own key is used for development and testing | Testing budget about $5 |
| Continuous integration | Deferred (decided 2026-10-20). The poisoning suite runs locally in the full test suite before each phase is committed; revisit CI when there are collaborators or customers | Deviation from firewall.md ("run it in CI") |
| ORM | None. Plain SQL migrations in `supabase/migrations/` via Supabase CLI | Python DB driver chosen when first needed |

## OPEN (ask before choosing)
| Area | Options under consideration | Blocks |
|---|---|---|
| Dashboard login | Supabase Auth, custom, or Clerk | Block L |
| Open vs closed source, licence | Decide after the product is built; repo stays private until then | Repo structure, licence file |
| Object storage for traces | Supabase Storage likely | Trace archive |
