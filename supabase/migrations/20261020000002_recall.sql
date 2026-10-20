-- Phase 6 recall: settings, recall log, learning-loop state, read access for the API.
--
--   * projects.holdout_rate: share of runs that get no memory (default 10%).
--   * agents.recall_threshold: minimum gate score (default 0.72; docs/recall-gating.md).
--   * playbooks.confidence: average confidence of the outcomes that support it.
--   * recalls: every recall answered, linked to the run that follows (by run id).
--   * runs.recall_counted_as: which outcome was already counted towards the recalled
--     playbooks' uses/successes, so the learning loop never double counts.
--   * retrack_api may read only ACTIVE playbooks (and failure signatures) of its project.

alter table public.projects
  add column holdout_rate real not null default 0.10 check (holdout_rate between 0 and 1);

alter table public.agents
  add column recall_threshold real not null default 0.72
    check (recall_threshold between 0 and 1);

alter table public.playbooks
  add column confidence real not null default 1.0 check (confidence between 0 and 1);

alter table public.runs
  add column recall_counted_as text check (recall_counted_as in ('success', 'failure'));

create table public.recalls (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  agent_id uuid not null,
  run_id uuid,
  playbook_ids uuid[] not null default '{}',
  warning_ids uuid[] not null default '{}',
  holdout boolean not null default false,
  mode text not null check (mode in ('hybrid', 'keyword', 'holdout', 'no_agent')),
  latency_ms integer,
  created_at timestamptz not null default now(),
  foreign key (agent_id, project_id) references public.agents (id, project_id)
);

create index recalls_run_idx on public.recalls (project_id, run_id);

alter table public.recalls enable row level security;
revoke all on public.recalls from anon, authenticated;

grant select, insert on public.recalls to retrack_api;
grant select on public.recalls to retrack_pipeline;
grant select on public.playbooks, public.failure_signatures to retrack_api;
grant update (recall_counted_as) on public.runs to retrack_pipeline;

create policy project_isolation on public.recalls for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());
create policy pipeline_project_isolation on public.recalls for select to retrack_pipeline
  using (project_id = private.current_project_id());

-- The internet-facing API only ever sees memory that passed the promotion rule.
create policy api_active_only on public.playbooks for select to retrack_api
  using (project_id = private.current_project_id() and status = 'active');
create policy api_project_isolation on public.failure_signatures for select to retrack_api
  using (project_id = private.current_project_id());
