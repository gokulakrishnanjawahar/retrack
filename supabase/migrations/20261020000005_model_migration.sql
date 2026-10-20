-- Phase 10 model migration (docs/regression-migration.md, "Model migration").
--
--   * migration_reports: one replay of the eval cases against a new model, run by
--     `retrack migrate` on the customer's side; summary holds the per-item report.
--   * eval_results.migration_id links results to their report. Migration results do not
--     touch eval_cases.last_result, which tracks the current model.
--   * private.validate_playbook_model: the only way to add a model to a playbook's
--     validated_models (the API role still cannot edit playbooks).

create table public.migration_reports (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  agent_id uuid not null,
  from_model text,
  to_model text not null,
  model_applied boolean not null default true,
  status text not null default 'running' check (status in ('running', 'completed')),
  summary jsonb not null default '{}',
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (id, project_id),
  foreign key (agent_id, project_id) references public.agents (id, project_id)
);

alter table public.eval_results add column migration_id uuid;
alter table public.eval_results
  add constraint eval_results_migration_fk foreign key (migration_id, project_id)
  references public.migration_reports (id, project_id) on delete cascade;

create function private.validate_playbook_model(
  p_project_id uuid, p_playbook_id uuid, p_model text
) returns void
language sql
security definer
set search_path = ''
as $$
  update public.playbooks
     set validated_models = array_append(validated_models, p_model)
   where project_id = p_project_id and id = p_playbook_id
     and not (p_model = any(validated_models))
$$;

revoke all on function private.validate_playbook_model(uuid, uuid, text)
  from public, anon, authenticated;
grant execute on function private.validate_playbook_model(uuid, uuid, text) to retrack_api;

alter table public.migration_reports enable row level security;
revoke all on public.migration_reports from anon, authenticated;
grant select, insert on public.migration_reports to retrack_api;
grant update (status, summary, completed_at) on public.migration_reports to retrack_api;
create policy project_isolation on public.migration_reports for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());
