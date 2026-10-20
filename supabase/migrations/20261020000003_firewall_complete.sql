-- Phase 8: complete memory firewall.
--
--   * firewall_findings: every flag the firewall raises (which check, how severe, why),
--     for runs and playbooks; the audit trail behind quarantine and review.
--   * review_queue gains who resolved an item and a note.
--   * private.record_finding: the one way the worker and pipeline roles write findings.

create table public.firewall_findings (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  object_type text not null check (object_type in ('run', 'playbook')),
  object_id uuid not null,
  check_name text not null check (
    check_name in ('injection_heuristic', 'injection_classifier', 'anomaly', 'instruction_shaped')
  ),
  severity text not null check (severity in ('flag', 'block')),
  detail text not null,
  created_at timestamptz not null default now()
);

create index firewall_findings_object_idx
  on public.firewall_findings (project_id, object_type, object_id);

alter table public.firewall_findings enable row level security;
revoke all on public.firewall_findings from anon, authenticated, retrack_api;
grant select on public.firewall_findings to retrack_pipeline;
create policy pipeline_project_isolation on public.firewall_findings for select
  to retrack_pipeline using (project_id = private.current_project_id());

alter table public.review_queue
  add column reviewer text,
  add column resolution_note text;

create function private.record_finding(
  p_project_id uuid,
  p_object_type text,
  p_object_id uuid,
  p_check_name text,
  p_severity text,
  p_detail text
) returns void
language sql
security definer
set search_path = ''
as $$
  insert into public.firewall_findings
    (project_id, object_type, object_id, check_name, severity, detail)
  values (p_project_id, p_object_type, p_object_id, p_check_name, p_severity, left(p_detail, 1000))
$$;

revoke all on function private.record_finding(uuid, text, uuid, text, text, text)
  from public, anon, authenticated;
grant execute on function private.record_finding(uuid, text, uuid, text, text, text)
  to retrack_worker, retrack_pipeline;
