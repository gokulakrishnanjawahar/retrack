-- Phase 9 regression: memory doubles as tests (docs/regression-migration.md).
--
--   * eval_cases: one per active playbook (the run must complete and use the playbook's
--     tools in order) and one per failure signature seen at least twice (that tool must
--     not fail with that error again; critical by default).
--   * Created and retired by triggers, so every path (auto-promotion, human approval,
--     retirement) keeps tests in step with memory.
--   * eval_results: history of `retrack test` runs; eval_cases keeps the latest result.
--   * The API role reads cases and records results for its own project only.

create table public.eval_cases (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  agent_id uuid not null,
  source text not null check (source in ('playbook', 'failure')),
  source_id uuid not null,
  source_version integer,
  input jsonb not null,
  expected_assertions jsonb not null,
  critical boolean not null default false,
  status text not null default 'active' check (status in ('active', 'retired')),
  last_result text check (last_result in ('passed', 'failed')),
  last_model_id text,
  last_run_at timestamptz,
  created_at timestamptz not null default now(),
  unique (project_id, source, source_id),
  unique (id, project_id),
  foreign key (agent_id, project_id) references public.agents (id, project_id)
);

create table public.eval_results (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null,
  eval_case_id uuid not null,
  test_run_id uuid not null,
  passed boolean not null,
  model_id text,
  details jsonb not null default '{}',
  created_at timestamptz not null default now(),
  foreign key (eval_case_id, project_id) references public.eval_cases (id, project_id)
    on delete cascade
);

create index eval_results_case_idx on public.eval_results (project_id, eval_case_id, created_at);

-- Triggers --------------------------------------------------------------------------

create function private.sync_playbook_eval_case() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.status = 'active' and (tg_op = 'INSERT' or old.status is distinct from 'active') then
    insert into public.eval_cases
      (project_id, agent_id, source, source_id, source_version, input, expected_assertions)
    values (
      new.project_id,
      new.agent_id,
      'playbook',
      new.id,
      new.version,
      jsonb_build_object('task', coalesce(
        (select r.task_text from public.provenance pv
           join public.runs r on r.project_id = pv.project_id and r.id = pv.source_run_ids[1]
          where pv.project_id = new.project_id and pv.object_type = 'playbook'
            and pv.object_id = new.id),
        nullif(new.task_pattern, ''),
        new.title)),
      jsonb_build_array(
        jsonb_build_object('type', 'completes'),
        jsonb_build_object('type', 'tool_sequence', 'tools', coalesce(
          (select jsonb_agg(s -> 'tool') from jsonb_array_elements(new.steps) s
            where coalesce(s ->> 'tool', '') not in ('', 'none')),
          '[]'::jsonb)))
    )
    on conflict (project_id, source, source_id) do update
      set status = 'active',
          source_version = excluded.source_version,
          expected_assertions = excluded.expected_assertions;
  elsif tg_op = 'UPDATE' and old.status = 'active' and new.status <> 'active' then
    update public.eval_cases set status = 'retired'
     where project_id = new.project_id and source = 'playbook' and source_id = new.id;
  end if;
  return new;
end
$$;

create trigger playbooks_sync_eval_case
  after insert or update of status on public.playbooks
  for each row execute function private.sync_playbook_eval_case();

create function private.sync_failure_eval_case() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.occurrences >= 2 then
    insert into public.eval_cases
      (project_id, agent_id, source, source_id, input, expected_assertions, critical)
    values (
      new.project_id,
      new.agent_id,
      'failure',
      new.id,
      jsonb_build_object('task', coalesce(
        (select r.task_text from public.runs r
          where r.project_id = new.project_id and r.id = new.example_run_id),
        new.tool_name || ' task')),
      jsonb_build_array(jsonb_build_object(
        'type', 'no_failure', 'tool', new.tool_name, 'error_class', new.error_class)),
      true
    )
    on conflict (project_id, source, source_id) do nothing;
  end if;
  return new;
end
$$;

create trigger failure_signatures_sync_eval_case
  after insert or update of occurrences on public.failure_signatures
  for each row execute function private.sync_failure_eval_case();

-- Privileges and row-level security ---------------------------------------------------

alter table public.eval_cases enable row level security;
alter table public.eval_results enable row level security;
revoke all on public.eval_cases, public.eval_results from anon, authenticated;

grant select on public.eval_cases to retrack_api;
grant update (last_result, last_model_id, last_run_at) on public.eval_cases to retrack_api;
grant select, insert on public.eval_results to retrack_api;

create policy project_isolation on public.eval_cases for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());
create policy project_isolation on public.eval_results for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());
