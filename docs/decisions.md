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
| Repo | Monorepo | Keep `sdk/` independent of `server/`, so the connector can be published on its own |
| Source | Closed source for now (Gokul, 2026-10-23). Server, pipelines, dashboard and migrations stay private | May be revisited later |
| Distribution | Hosted SaaS, like Supermemory (Gokul, 2026-10-23). Customers sign up in the dashboard and get an API key; the only thing they install is the thin client connector in `sdk/` | API-only (no package) and an LLM proxy were considered; a proxy may come with the production SaaS |
| Connector package | Published on PyPI as `retrack-ai` (import name stays `retrack`; `retrack` on PyPI belongs to an unrelated project), MIT licence (Gokul, 2026-10-23) | The licence covers the connector only. Who runs the publish is not decided yet |
| Python tooling | uv, pytest, ruff | |
| Developer OS | macOS (Apple Silicon) | |
| Git | GitHub remote: gokulakrishnanjawahar/retrack, branch `main`; private | Closed source (see Source) |
| Pricing | Not decided; out of scope for code | Only record usage |
| Phase order | See `plan.md` (2026-10-15) | Change only with Gokul's approval |
| Local development | Dev Supabase cloud project (no Docker); migrations applied with Supabase CLI `db push` | Tests that need a database run against it |
| Backend framework | FastAPI (Python) | Portable across hosts |
| Hosting | Vercel, region `bom1` (Mumbai), same region as the database | Hobby (free) while building; Pro required at launch (commercial use) |
| Worker trigger | Supabase Cron (`pg_cron` + `pg_net`) calls a secret-protected `/internal/drain` endpoint every minute | Free; defined in SQL migrations. GitHub Actions and Vercel Hobby cron rejected (too slow) |
| LLM (judge, distiller, firewall classifier) | Claude Haiku 5.5 (Anthropic), low effort by default; raise effort per job only if evals show it helps. All calls go through a provider-agnostic `LLMClient` interface | Decided 2026-10-19. Prompts stay under 100k tokens (cheaper price tier). Compared against Gemini 2.5 Flash-Lite, which is lower quality and being retired |
| Embedding model | `gemini-embedding-2` on Google Vertex AI, **global endpoint** (`location=global`), 1,536 dimensions, behind an `Embedder` interface (Gokul, 2026-10-24) | First decided 2026-10-19 as `gemini-embedding-001` in `asia-south1` (Mumbai) for speed and India-only processing. Changed before any production vector existed: on 2026-10-24 Vertex served Embedding 2 only from `global` (404 in `asia-south1`), and a new project's quota for `gemini-embedding-001` is 5 requests per minute project-wide (Embedding 2: 300,000), far too few for recall. Trade-off accepted: text may be processed outside India (paid Vertex still never trains on it). The two models' vectors are not comparable; the model is recorded per vector. Recall always searches by meaning; keyword-only search and the free Gemini API (AI Studio) were rejected (Gokul, 2026-10-23). Measure recall's embedding time from Vercel; if it often exceeds recall's 150 ms limit, revisit the limit or the model |
| Google Cloud account and sign-in | Paid Cloud Billing account on Gokul's card (no free trial, no prepayment), with a ₹100/month **spend cap** on the Vertex AI service; Vercel signs in keylessly through Workload Identity Federation (pool and provider `vercel`, service account `retrack-embeddings` with Vertex AI User only) (Gokul, 2026-10-24) | Details in `architecture.md` (Keyless Google sign-in). No Google key exists; key creation is blocked by org policy. Identifiers are in Gokul's private, git-ignored `GOOGLE_CLOUD.md` |
| LLM provider for the prototype | Anthropic (Claude Haiku 5.5) on Retrack's own key, about $2 of credit; switch to OpenRouter when it runs out (Gokul, 2026-10-23) | Needs an OpenRouter implementation of `LLMClient` before the switch. When credit runs out, runs are retried 5 times, then stay `unknown` without judging or learning (nothing breaks, but nothing is learned) |
| LLM keys at launch | Customers can bring their own LLM key (encrypted, never logged); Retrack's own key is used for development and testing | Testing budget about $5 |
| Continuous integration | Deferred (decided 2026-10-20). The poisoning suite runs locally in the full test suite before each phase is committed; revisit CI when there are collaborators or customers | Deviation from firewall.md ("run it in CI") |
| AI-judged eval assertions | Deferred until customers can bring their own LLM key (decided 2026-10-20) | `retrack test` checks tools, order, known failures and expected text deterministically |
| Retention vs provenance | Runs supporting a live playbook are kept until it is retired; all other runs follow `retention_days` (decided 2026-10-21, may be revisited) | Keeps live memory traceable to its sources |
| Ingest rate limit | 600 runs per minute per project by default (`projects.ingest_rate_limit`) | Fixed one-minute windows in `ingest_counters` |
| Dashboard login | Supabase Auth (decided 2026-10-21) | Same database; row-level security uses the logged-in user; no extra vendor |
| Dashboard design goal | Dynamic and instantly attractive and credible (Gokul, 2026-10-21) | Live elements, motion, polished data visualisation |
| Logo | "Return ring": an open ring around a solid core, monochrome, with the lowercase wordmark "retrack" (Gokul, 2026-10-22) | Chosen from six monochrome options; the browser icon is the white ring on a black tile |
| Dashboard visual style | Dark premium developer tool (Gokul, 2026-10-21) | Near-black canvas, hairline borders, one violet signal colour; Geist; Motion animations; dark only |
| Dashboard data access | Supabase client as the signed-in user, RLS for reads, `public.dashboard_*` functions for writes (2026-10-21) | Functions live in `public` with a `dashboard_` prefix rather than a separate exposed schema, so no API settings change is needed. No service-role key in the dashboard |
| Playbook rollback | Built in Phase 13, dashboard only (owner or admin) | Restores a version's content and its embedding as a new version, so a rollback can itself be undone |
| API key write access | Read memory, quarantine and retire only (Gokul, 2026-10-21) | Approve and rollback need a person in the dashboard: a leaked or prompt-injected agent key must never put memory into service (CLAUDE.md rule 8). `PATCH /v1/playbooks/{id}` answers 403 for them |
| Fleet sharing rules | Owners and admins propose ACTIVE playbooks to another agent of the same project, as a new playbook or an update of one of its playbooks; approval by an owner or admin activates it (2026-10-21) | A copy starts with no uses (support 1), keeps the source's confidence and tool versions, and is not yet validated on any model (no plan replay until it is). An update is refused if the target changed after the proposal, and approval is refused if the source left service (retired or quarantined) since. Approving an update closes the target's open reviews. Any content change (approved update, rollback) clears `validated_models`, so plan replay waits until `retrack migrate` validates the new steps. The reviewer sees tools the target agent never used and untrusted sources |
| ORM | None. Plain SQL migrations in `supabase/migrations/` via Supabase CLI | Python DB driver chosen when first needed |

## OPEN (ask before choosing)
| Area | Options under consideration | Blocks |
|---|---|---|
| Object storage for traces | Supabase Storage likely | Trace archive |
