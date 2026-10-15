-- Phase 1 foundation: tenancy, API keys, runs, steps, usage counters, row-level security.
--
-- Access model
--   * The server runs every request as role `retrack_api` inside a transaction that sets
--     `app.project_id`. RLS policies only expose rows of that project.
--   * Supabase's public API roles (anon, authenticated) get no access to these tables.
--     Per-user dashboard policies arrive with the dashboard login decision (Phase 12).
--   * Admin work (creating projects and API keys) runs as the database owner.
--   * `task_embedding` on runs is added in Phase 5, once the embedding model sets its dimension.

create schema private;

create role retrack_api nologin noinherit;
grant retrack_api to postgres;
grant usage on schema public, private to retrack_api;

create function private.current_project_id() returns uuid
language sql stable
set search_path = ''
as $$ select nullif(current_setting('app.project_id', true), '')::uuid $$;

-- Tenancy ------------------------------------------------------------------------------

create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table public.projects (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  name text not null,
  region text not null default 'ap-south-1',
  retention_days integer not null default 90 check (retention_days > 0),
  created_at timestamptz not null default now()
);

-- user_id has no foreign key until the dashboard login provider is decided.
create table public.members (
  org_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid not null,
  role text not null,
  primary key (org_id, user_id)
);

create table public.agents (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  name text not null,
  framework text not null default 'langgraph',
  created_at timestamptz not null default now(),
  unique (project_id, name),
  unique (id, project_id)
);

create table public.api_keys (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  prefix text not null unique,
  key_hash text not null,
  name text not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);

-- Runs ---------------------------------------------------------------------------------

-- The run id is client-generated and is the idempotency key. It is unique per project,
-- so one tenant can never block or collide with another tenant's run ids.
create table public.runs (
  project_id uuid not null references public.projects (id) on delete cascade,
  id uuid not null,
  agent_id uuid not null,
  task_text text not null,
  model_id text not null,
  tool_versions jsonb not null default '{}',
  outcome text not null default 'unknown' check (outcome in ('success', 'failure', 'unknown')),
  outcome_source text check (outcome_source in ('test', 'feedback', 'event', 'judge')),
  confidence real check (confidence between 0 and 1),
  tokens_in integer not null default 0,
  tokens_out integer not null default 0,
  cost_usd numeric(12, 6),
  latency_ms integer,
  taint_level text not null default 'untrusted'
    check (taint_level in ('trusted', 'untrusted', 'quarantined')),
  holdout boolean not null default false,
  recalled_playbook_ids uuid[] not null default '{}',
  trace_uri text,
  created_at timestamptz not null default now(),
  primary key (project_id, id),
  foreign key (agent_id, project_id) references public.agents (id, project_id)
);

create index runs_project_created_idx on public.runs (project_id, created_at);
create index runs_task_text_fts_idx on public.runs using gin (to_tsvector('english', task_text));

create table public.steps (
  project_id uuid not null,
  run_id uuid not null,
  idx integer not null check (idx >= 0),
  type text not null check (type in ('llm', 'tool')),
  tool_name text,
  args_hash text,
  args_redacted jsonb,
  result_class text,
  error_class text,
  latency_ms integer,
  tokens_in integer,
  tokens_out integer,
  input_trust text not null default 'untrusted' check (input_trust in ('trusted', 'untrusted')),
  primary key (project_id, run_id, idx),
  foreign key (project_id, run_id) references public.runs (project_id, id) on delete cascade
);

-- Usage metering -----------------------------------------------------------------------

create table public.usage_daily (
  project_id uuid not null references public.projects (id) on delete cascade,
  day date not null,
  runs_captured bigint not null default 0,
  recalls_served bigint not null default 0,
  distillations bigint not null default 0,
  tokens_processed bigint not null default 0,
  primary key (project_id, day)
);

-- Adds to today's counters (UTC) for the project set in `app.project_id`.
create function private.increment_usage(
  p_runs_captured bigint default 0,
  p_recalls_served bigint default 0,
  p_distillations bigint default 0,
  p_tokens_processed bigint default 0
) returns void
language sql
set search_path = ''
as $$
  insert into public.usage_daily as u
    (project_id, day, runs_captured, recalls_served, distillations, tokens_processed)
  values (
    private.current_project_id(), (now() at time zone 'utc')::date,
    p_runs_captured, p_recalls_served, p_distillations, p_tokens_processed
  )
  on conflict (project_id, day) do update set
    runs_captured = u.runs_captured + excluded.runs_captured,
    recalls_served = u.recalls_served + excluded.recalls_served,
    distillations = u.distillations + excluded.distillations,
    tokens_processed = u.tokens_processed + excluded.tokens_processed
$$;

-- API key verification -----------------------------------------------------------------

-- Runs before the project is known, so it is the only way `retrack_api` touches api_keys.
-- Returns the key's project id, or null when the key is unknown, wrong or revoked.
create function private.verify_api_key(p_prefix text, p_key_hash text) returns uuid
language sql
security definer
set search_path = ''
as $$
  update public.api_keys
     set last_used_at = now()
   where prefix = p_prefix and key_hash = p_key_hash and revoked_at is null
  returning project_id
$$;

-- Privileges ---------------------------------------------------------------------------

revoke all on all tables in schema public from anon, authenticated;
-- Tables and functions created by later migrations also start with no public-API access.
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on functions from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;
revoke all on all functions in schema private from public, anon, authenticated;

grant select on public.projects to retrack_api;
grant select, insert, update on public.agents, public.runs, public.steps to retrack_api;
grant select, insert, update on public.usage_daily to retrack_api;
grant execute on function private.current_project_id() to retrack_api;
grant execute on function private.increment_usage(bigint, bigint, bigint, bigint) to retrack_api;
grant execute on function private.verify_api_key(text, text) to retrack_api;

-- Row-level security -------------------------------------------------------------------

alter table public.organizations enable row level security;
alter table public.members enable row level security;
alter table public.api_keys enable row level security;
alter table public.projects enable row level security;
alter table public.agents enable row level security;
alter table public.runs enable row level security;
alter table public.steps enable row level security;
alter table public.usage_daily enable row level security;

create policy project_isolation on public.projects for select to retrack_api
  using (id = private.current_project_id());

create policy project_isolation on public.agents for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());

create policy project_isolation on public.runs for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());

create policy project_isolation on public.steps for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());

create policy project_isolation on public.usage_daily for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());
