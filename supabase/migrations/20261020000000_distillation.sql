-- Phase 5 distillation: playbooks, failure signatures, provenance, review queue, embeddings.
--
-- Roles
--   * retrack_pipeline: the background pipeline that turns runs into memory. It reads runs
--     and writes memory tables, always inside one project (RLS on app.project_id).
--     The internet-facing retrack_api role cannot write memory at all.
-- Vectors
--   * gemini-embedding-001 at 1,536 dimensions, stored as half precision (halfvec) to fit
--     Supabase's free tier; cosine distance; HNSW indexes.
-- Promotion rule (docs/firewall.md)
--   * A trigger refuses status 'active' unless a human approved, or the playbook has enough
--     independent trusted support and no source needs review (see playbook_can_activate).

create extension if not exists vector with schema extensions;

create role retrack_pipeline nologin noinherit;
grant retrack_pipeline to retrack_server;
grant retrack_pipeline to postgres;
grant usage on schema public, private, extensions to retrack_pipeline;
grant usage on schema extensions to retrack_api;
grant execute on function private.current_project_id() to retrack_pipeline;
grant execute on function private.increment_usage(bigint, bigint, bigint, bigint) to retrack_pipeline;
alter role retrack_server set search_path = "$user", public, extensions;

-- Runs: task embeddings and distillation state ----------------------------------------

alter table public.runs
  add column task_embedding extensions.halfvec(1536),
  add column embedding_model text,
  add column distilled_at timestamptz,
  add column distilled_as text check (distilled_as in ('success', 'failure', 'skipped'));

-- Embedding cache (docs/constraints.md: never re-embed unchanged text) -------------------

create table public.embedding_cache (
  project_id uuid not null references public.projects (id) on delete cascade,
  model text not null,
  content_hash text not null,
  embedding extensions.halfvec(1536) not null,
  created_at timestamptz not null default now(),
  primary key (project_id, model, content_hash)
);

-- Playbooks ----------------------------------------------------------------------------

create table public.playbooks (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  agent_id uuid not null,
  version integer not null default 1,
  status text not null default 'candidate'
    check (status in ('candidate', 'active', 'quarantined', 'retired')),
  title text not null,
  task_pattern text not null default '',
  preconditions text not null default '',
  steps jsonb not null default '[]',
  pitfalls text not null default '',
  embedding extensions.halfvec(1536),
  embedding_model text,
  -- Evidence from distillation (runs whose success supports this playbook).
  support_count integer not null default 0,
  trusted_support integer not null default 0,
  untrusted_sources integer not null default 0,
  quarantined_sources integer not null default 0,
  passed_automatic_checks boolean not null default false,
  -- Results after recall (Phase 6).
  uses integer not null default 0,
  successes integer not null default 0,
  success_rate real not null default 0,
  last_success_at timestamptz,
  validated_models text[] not null default '{}',
  tool_versions jsonb not null default '{}',
  content_hash text not null,
  approved_by text,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  search_text tsvector generated always as (
    to_tsvector('english', title || ' ' || task_pattern || ' ' || preconditions || ' ' || pitfalls)
  ) stored,
  unique (id, project_id),
  foreign key (agent_id, project_id) references public.agents (id, project_id)
);

create index playbooks_lookup_idx on public.playbooks (project_id, agent_id, status);
create index playbooks_embedding_idx on public.playbooks
  using hnsw (embedding extensions.halfvec_cosine_ops);
create index playbooks_search_idx on public.playbooks using gin (search_text);
create index runs_task_embedding_idx on public.runs
  using hnsw (task_embedding extensions.halfvec_cosine_ops);

create table public.playbook_versions (
  project_id uuid not null,
  playbook_id uuid not null,
  version integer not null,
  snapshot jsonb not null,
  change_reason text not null,
  created_at timestamptz not null default now(),
  primary key (playbook_id, version),
  foreign key (playbook_id, project_id) references public.playbooks (id, project_id)
    on delete cascade
);

-- Failure signatures -------------------------------------------------------------------

create table public.failure_signatures (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  agent_id uuid not null,
  tool_name text not null,
  error_class text not null,
  input_shape text not null,
  fingerprint text not null,
  occurrences integer not null default 1,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  example_run_id uuid,
  recovery_playbook_id uuid,
  unrecoverable boolean not null default false,
  unique (project_id, fingerprint),
  foreign key (agent_id, project_id) references public.agents (id, project_id)
);

-- Provenance and review ----------------------------------------------------------------

create table public.provenance (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  object_type text not null check (object_type in ('playbook', 'failure_signature')),
  object_id uuid not null,
  source_run_ids uuid[] not null default '{}',
  input_sources text[] not null default '{}',
  trust_level text not null check (trust_level in ('trusted', 'untrusted', 'quarantined')),
  reviewer_id text,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, object_type, object_id)
);

create table public.review_queue (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  object_type text not null check (object_type in ('playbook', 'failure_signature')),
  object_id uuid not null,
  reason text not null,
  status text not null default 'open' check (status in ('open', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create index review_queue_open_idx on public.review_queue (project_id, status);

-- Promotion guard ----------------------------------------------------------------------

-- Mirrors retrack_server.firewall.promotion_allowed (REQUIRED_TRUSTED_SUCCESSES = 3).
create function private.playbook_can_activate(p public.playbooks) returns boolean
language sql immutable
set search_path = ''
as $$
  select case
    when p.approved_at is not null then true
    when p.quarantined_sources > 0 then false
    when p.untrusted_sources > 0 and not p.passed_automatic_checks then false
    else p.trusted_support >= 3
  end
$$;

create function private.guard_playbook_activation() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.status = 'active'
     and (tg_op = 'INSERT' or old.status is distinct from 'active')
     and not private.playbook_can_activate(new) then
    raise exception 'playbook % cannot become active: promotion rule not met', new.id
      using errcode = 'check_violation';
  end if;
  new.updated_at := now();
  return new;
end
$$;

create trigger playbooks_guard_activation
  before insert or update on public.playbooks
  for each row execute function private.guard_playbook_activation();

-- Privileges and row-level security ---------------------------------------------------

revoke all on public.embedding_cache, public.playbooks, public.playbook_versions,
  public.failure_signatures, public.provenance, public.review_queue
  from anon, authenticated, retrack_api;

grant select on public.projects, public.agents, public.runs, public.steps,
  public.outcome_signals to retrack_pipeline;
grant update (task_embedding, embedding_model, distilled_at, distilled_as)
  on public.runs to retrack_pipeline;
grant select, insert, update on public.usage_daily to retrack_pipeline;
grant select, insert on public.embedding_cache to retrack_pipeline;
grant select, insert, update on public.playbooks, public.playbook_versions,
  public.failure_signatures, public.provenance, public.review_queue to retrack_pipeline;

alter table public.embedding_cache enable row level security;
alter table public.playbooks enable row level security;
alter table public.playbook_versions enable row level security;
alter table public.failure_signatures enable row level security;
alter table public.provenance enable row level security;
alter table public.review_queue enable row level security;

do $$
declare
  t text;
begin
  foreach t in array array[
    'agents', 'runs', 'steps', 'outcome_signals', 'usage_daily', 'embedding_cache',
    'playbooks', 'playbook_versions', 'failure_signatures', 'provenance', 'review_queue'
  ] loop
    execute format(
      'create policy pipeline_project_isolation on public.%I for all to retrack_pipeline'
      ' using (project_id = private.current_project_id())'
      ' with check (project_id = private.current_project_id())',
      t
    );
  end loop;
end
$$;

create policy pipeline_project_isolation on public.projects for select to retrack_pipeline
  using (id = private.current_project_id());
